"""
메인 폴링 루프.
채널별 라이브 상태를 주기적으로 확인하고
방송 시작/종료 이벤트를 처리합니다.
"""
import asyncio
from datetime import datetime, timezone
from src.config import settings
from src.watcher.live_detector import check_channel_live
from src.watcher.chat_collector import ChatCollector
from src.watcher.caption_watcher import fetch_captions
from src.watcher.video_detector import get_new_videos, get_latest_video_id
from src.storage import database as db
from src.storage import store
from src.pipeline.preprocessor import build_caption_text, build_chat_text
from src.pipeline.summarizer import summarize
from src.pipeline.reporter import build_report
from src.pipeline.video_summarizer import summarize_video
from src.notifiers import slack_notifier, notion_notifier
from src.utils.logger import get_logger

logger = get_logger(__name__)

_broadcast = None
_runtime_channels: set[str] = set()  # UI에서 동적으로 추가/제거된 채널 ID


def set_broadcast(fn):
    global _broadcast
    _broadcast = fn


async def _emit(event: dict):
    if _broadcast:
        await _broadcast(event)

# 채널별 현재 상태 추적: {channel_id: {"session_id": ..., "chat": ChatCollector, ...}}
_active_sessions: dict[str, dict] = {}


async def _handle_live_start(channel_id: str, live_info: dict):
    """라이브 방송 시작 처리."""
    video_id = live_info["video_id"]
    session_id = f"{channel_id}_{video_id}"

    if channel_id in _active_sessions:
        # 이미 추적 중인 세션
        return

    logger.info("[START] 라이브 감지: %s | %s", live_info["channel_title"], live_info["title"])

    session = {
        "id": session_id,
        "channel_id": channel_id,
        "channel_title": live_info["channel_title"],
        "video_id": video_id,
        "title": live_info["title"],
        "started_at": live_info["actual_start_time"],
        "status": "live",
        "peak_viewers": live_info["concurrent_viewers"],
    }
    await db.upsert_session(session)
    await _emit({"type": "live_start", "session": session})

    chat = ChatCollector(video_id=video_id, session_id=session_id)
    chat.init()

    _active_sessions[channel_id] = {
        "session_id": session_id,
        "video_id": video_id,
        "started_at": live_info["actual_start_time"],
        "chat": chat,
        "peak_viewers": live_info["concurrent_viewers"],
    }


async def _collect_chat(channel_id: str, current_viewers: int):
    """방송 중 채팅 수집."""
    state = _active_sessions.get(channel_id)
    if not state:
        return

    state["peak_viewers"] = max(state["peak_viewers"], current_viewers)
    messages = state["chat"].collect_page()
    if messages:
        await db.insert_chat_messages(messages)
        logger.debug("채팅 %d건 수집 (channel=%s)", len(messages), channel_id)
        await _emit({
            "type": "chat_collected",
            "session_id": state["session_id"],
            "count": len(messages),
            "viewers": current_viewers,
        })


async def _handle_live_end(channel_id: str):
    """라이브 방송 종료 처리 → 요약 파이프라인 실행."""
    state = _active_sessions.pop(channel_id, None)
    if not state:
        return

    session_id = state["session_id"]
    video_id = state["video_id"]
    ended_at = datetime.now(timezone.utc).isoformat()

    started_dt = datetime.fromisoformat(state["started_at"].replace("Z", "+00:00"))
    ended_dt = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
    duration_secs = int((ended_dt - started_dt).total_seconds())

    logger.info("[END] 방송 종료 (session=%s, duration=%ds)", session_id, duration_secs)

    await db.close_session(session_id, ended_at, duration_secs)
    await _emit({"type": "live_end", "session_id": session_id, "duration_secs": duration_secs})

    # 세션 정보 갱신
    session = await db.get_session(session_id)
    if not session:
        return
    session["peak_viewers"] = state["peak_viewers"]

    # 요약 파이프라인을 별도 태스크로 실행 (폴링 블로킹 방지)
    asyncio.create_task(_run_summary_pipeline(video_id, session))


async def _run_summary_pipeline(video_id: str, session: dict):
    """종료 후 요약 파이프라인."""
    session_id = session["id"]
    logger.info("요약 파이프라인 시작 (session=%s)", session_id)

    # 자막 수집 (동기 함수 → 스레드 풀)
    loop = asyncio.get_event_loop()
    captions_raw = await loop.run_in_executor(None, fetch_captions, video_id)
    await db.insert_captions(session_id, captions_raw)

    # 텍스트 빌드
    captions_db = await db.get_captions(session_id)
    chat_db = await db.get_chat_messages(session_id)
    caption_text = build_caption_text(captions_db)
    chat_text = build_chat_text(chat_db)

    # Claude 요약 (동기 API → 스레드 풀)
    summary = await loop.run_in_executor(None, summarize, caption_text, chat_text, session)
    await store.save_summary(session_id, session, summary)

    # 리포트 생성
    report_md = build_report(session, summary)

    # 파일 저장
    import os
    os.makedirs("./reports", exist_ok=True)
    safe_title = "".join(c for c in session.get("title", "report") if c.isalnum() or c in " _-")[:50]
    report_path = f"./reports/{session_id}_{safe_title}.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_md)
    logger.info("리포트 저장: %s", report_path)

    # 알림 전송
    await loop.run_in_executor(None, slack_notifier.send_summary, session, summary, report_md)
    await loop.run_in_executor(None, notion_notifier.save_to_notion, session, summary, report_md)

    await _emit({"type": "summary_ready", "session": session, "summary": summary})
    logger.info("요약 파이프라인 완료 (session=%s)", session_id)


async def _load_db_channels():
    """DB에 등록된 채널 ID를 _runtime_channels에 동기화."""
    import aiosqlite
    async with aiosqlite.connect(settings.db_path) as conn:
        async with conn.execute("SELECT channel_id FROM monitored_channels") as cur:
            rows = await cur.fetchall()
    for (cid,) in rows:
        _runtime_channels.add(cid)


async def _handle_new_video(video: dict):
    """신규 업로드 영상 감지 → 요약 파이프라인."""
    video_id = video["video_id"]
    logger.info("[VIDEO] 신규 영상 감지: %s | %s", video["channel_title"], video["title"])
    await _emit({"type": "video_detected", "video": video})
    asyncio.create_task(_run_video_summary_pipeline(video))


async def _run_video_summary_pipeline(video: dict):
    """업로드 영상 요약 파이프라인."""
    loop = asyncio.get_event_loop()
    video_id = video["video_id"]

    # 자막 수집
    captions_raw = await loop.run_in_executor(None, fetch_captions, video_id)
    captions = [{"start_sec": c["start"], "text": c["text"]} for c in captions_raw]

    # 요약
    summary = await loop.run_in_executor(None, summarize_video, video, captions)
    await store.save_video_summary(video, summary)

    # 리포트 저장
    import os, json as _json
    os.makedirs("./reports", exist_ok=True)
    safe = "".join(c for c in video.get("title","report") if c.isalnum() or c in " _-")[:50]
    report_path = f"./reports/video_{video_id}_{safe}.md"
    report_md = _build_video_report(video, summary)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    await _emit({"type": "video_summary_ready", "video": video, "summary": summary})
    logger.info("영상 요약 완료: %s", video.get("title", ""))


def _build_video_report(video: dict, summary: dict) -> str:
    import re
    iso = video.get("duration", "")
    m = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', iso)
    dur = ""
    if m:
        h, mn, s = m.group(1), m.group(2), m.group(3)
        if h:  dur += f"{h}시간 "
        if mn: dur += f"{mn}분 "
        if s:  dur += f"{s}초"

    topics = "\n".join(f"- {t}" for t in summary.get("key_topics", []))
    highlights = "\n".join(
        f"- [{hl.get('timestamp','')}] {hl.get('description','')}"
        for hl in summary.get("highlights", [])
    )
    url = f"https://www.youtube.com/watch?v={video['video_id']}"
    return f"""# 📹 신규 영상 요약

## {video.get('title','')}

| 항목 | 내용 |
|------|------|
| 채널 | {video.get('channel_title','')} |
| 영상 길이 | {dur} |
| 조회수 | {video.get('view_count',0):,} |
| 링크 | {url} |

---

## 한줄 요약
> {summary.get('one_liner','')}

## 전체 요약
{summary.get('summary_text','')}

## 핵심 주제
{topics}

## 주요 섹션
{highlights}

## 추천 대상
{summary.get('target_audience','')}
""".strip()


async def poll_once():
    """모든 채널 1회 폴링 (라이브 + 신규 영상)."""
    loop = asyncio.get_event_loop()
    all_channels = set(_runtime_channels)

    for channel_id in all_channels:
        # ── 라이브 감지 ──
        live_info = await loop.run_in_executor(None, check_channel_live, channel_id)
        if live_info:
            if channel_id not in _active_sessions:
                await _handle_live_start(channel_id, live_info)
            else:
                await _collect_chat(channel_id, live_info["concurrent_viewers"])
        else:
            if channel_id in _active_sessions:
                await _handle_live_end(channel_id)

        # ── 신규 영상 감지 ──
        last_id = await db.get_last_video_id(channel_id)

        if last_id is None:
            # 최초 실행 — 기준점만 저장하고 요약하지 않음
            init_id = await loop.run_in_executor(None, get_latest_video_id, channel_id)
            if init_id:
                await db.set_last_video_id(channel_id, init_id)
                logger.info("영상 기준점 설정 (channel=%s, video=%s)", channel_id, init_id)
        else:
            new_videos = await loop.run_in_executor(None, get_new_videos, channel_id, last_id)
            if new_videos:
                # 가장 최신 ID를 먼저 저장 (재시작 시 중복 방지)
                await db.set_last_video_id(channel_id, new_videos[0]["video_id"])
                for video in reversed(new_videos):  # 오래된 것부터 처리
                    await _handle_new_video(video)


async def run_polling_loop():
    """메인 폴링 루프."""
    interval = settings.poll_interval_seconds
    await _load_db_channels()
    logger.info("폴링 시작 (간격=%ds, 등록채널=%d개)", interval, len(_runtime_channels))

    while True:
        try:
            await poll_once()
        except Exception as e:
            logger.error("폴링 오류: %s", e, exc_info=True)
        await asyncio.sleep(interval)
