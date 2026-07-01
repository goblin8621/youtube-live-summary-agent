"""
FastAPI 서버: UI에 WebSocket으로 실시간 이벤트를 전달하고
REST API로 히스토리 및 채널 관리를 제공합니다.
"""
import asyncio
import json
import re
import aiosqlite
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path
from googleapiclient.errors import HttpError
from src.storage import database as db
from src.storage import store
from src.config import settings
from src.pipeline import ai_client
from src.watcher import youtube_client
from src.utils.logger import get_logger

logger = get_logger(__name__)
app = FastAPI(title="YouTube Live Summary Agent")

_connections: list[WebSocket] = []


async def broadcast(event: dict):
    """연결된 모든 클라이언트에 이벤트 전송."""
    dead = []
    for ws in _connections:
        try:
            await ws.send_text(json.dumps(event, ensure_ascii=False))
        except Exception:
            dead.append(ws)
    for ws in dead:
        _connections.remove(ws)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    _connections.append(websocket)
    logger.info("WebSocket 연결 (총 %d개)", len(_connections))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        _connections.remove(websocket)
        logger.info("WebSocket 해제 (총 %d개)", len(_connections))


@app.get("/api/history")
async def get_history():
    """최근 요약 목록 반환 (DB 모드: DB 조회 / 파일 모드: 파일 조회)."""
    return await store.get_history(limit=50)


@app.get("/api/live")
async def get_live_sessions():
    if not store.is_db_mode():
        from src.scheduler import poller as p
        return [
            {"id": v["session_id"], "channel_id": cid, "status": "live"}
            for cid, v in p._active_sessions.items()
        ]
    ids = await db.get_live_session_ids()
    sessions = []
    for sid in ids:
        s = await db.get_session(sid)
        if s:
            sessions.append(s)
    return sessions


# ── AI 설정 API ───────────────────────────────────────────

@app.get("/api/settings")
async def get_settings():
    """현재 AI + YouTube 설정 반환."""
    cfg = ai_client.get_config()
    yt_key = youtube_client.get_key()
    cfg["yt_key_masked"] = f"...{yt_key[-4:]}" if len(yt_key) > 4 else ("설정됨" if yt_key else "")
    return cfg


class SettingsUpdateRequest(BaseModel):
    provider: str = ""
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    youtube_api_key: str = ""


@app.put("/api/settings")
async def update_settings(req: SettingsUpdateRequest):
    """AI + YouTube 설정 변경 및 저장 (DB 모드: DB / 파일 모드: config.json)."""
    ai_client.update_config(
        provider=req.provider or None,
        model=req.model or None,
        api_key=req.api_key if req.api_key else None,
        base_url=req.base_url if req.base_url else None,
    )
    if req.youtube_api_key:
        youtube_client.set_key(req.youtube_api_key)

    cfg = ai_client._config
    updates: dict[str, dict[str, str]] = {
        "ai": {
            "provider": cfg["provider"],
            "model":    cfg["model"],
            "base_url": cfg["base_url"],
        }
    }
    if req.api_key:
        updates["ai"]["api_key"] = cfg["api_key"]
    if req.youtube_api_key:
        updates["youtube"] = {"api_key": req.youtube_api_key}

    await store.set_settings_many(updates)

    logger.info("설정 저장: provider=%s model=%s yt_key=%s",
                cfg["provider"], cfg["model"], bool(req.youtube_api_key))
    return await get_settings()


# ── 인증 검증 API ─────────────────────────────────────────

@app.get("/api/validate/youtube")
async def validate_youtube():
    """YouTube API 키 유효성 검사."""
    try:
        resp = youtube_client.get_client().channels().list(
            part="id", id="UCVHFbw7woebKtRljuCGF-ug", maxResults=1
        ).execute()
        return {"ok": True}
    except HttpError as e:
        code = e.resp.status
        if code == 403:
            return {"ok": False, "detail": "키가 유효하지 않거나 API가 비활성화됨"}
        if code == 400:
            return {"ok": False, "detail": "잘못된 요청 (키 형식 확인)"}
        return {"ok": False, "detail": f"YouTube API 오류 ({code})"}
    except Exception as e:
        return {"ok": False, "detail": "API 키 미설정"}


@app.get("/api/validate/ai")
async def validate_ai():
    """AI API 키 유효성 검사 (최소 호출로 인증 확인)."""
    loop = asyncio.get_event_loop()
    try:
        def _test():
            ai_client.chat(system="", user="hi", max_tokens=1)
        await loop.run_in_executor(None, _test)
        return {"ok": True}
    except Exception as e:
        msg = str(e)
        if "401" in msg or "authentication" in msg.lower() or "api_key" in msg.lower() or "invalid" in msg.lower() or "permission" in msg.lower():
            return {"ok": False, "detail": "API 키가 유효하지 않음"}
        if "model" in msg.lower() or "404" in msg:
            return {"ok": False, "detail": "모델명 확인 필요"}
        if "base_url" in msg.lower() or "connection" in msg.lower():
            return {"ok": False, "detail": "서버 연결 실패 (Base URL 확인)"}
        return {"ok": False, "detail": msg[:80]}


class ChannelCheckRequest(BaseModel):
    input: str


@app.post("/api/channels/check")
async def check_channel(req: ChannelCheckRequest):
    """채널 존재 여부만 확인 (추가하지 않음)."""
    channel_id = _resolve_channel_id(req.input)
    if not channel_id:
        raise HTTPException(status_code=404, detail="채널을 찾을 수 없습니다")
    try:
        resp = youtube_client.get_client().channels().list(
            part="snippet,statistics",
            id=channel_id,
            fields="items(id,snippet(title,thumbnails),statistics(subscriberCount))",
        ).execute()
        items = resp.get("items", [])
        if not items:
            raise HTTPException(status_code=404, detail="채널 정보를 가져올 수 없습니다")
        snippet = items[0]["snippet"]
        stats   = items[0].get("statistics", {})
        return {
            "channel_id": channel_id,
            "title": snippet.get("title", ""),
            "thumbnail_url": snippet.get("thumbnails", {}).get("default", {}).get("url", ""),
            "subscriber_count": int(stats.get("subscriberCount", 0)),
        }
    except HttpError as e:
        raise HTTPException(status_code=502, detail=f"YouTube API 오류: {e}")


# ── 채널 관리 API ──────────────────────────────────────────

@app.get("/api/channels")
async def list_channels():
    """등록된 채널 목록 반환 (DB 또는 파일 모드)."""
    return await store.get_channels()


class ChannelAddRequest(BaseModel):
    input: str  # 채널 URL, @핸들, 또는 채널 ID


def _resolve_channel_id(raw: str) -> str | None:
    """URL·핸들·ID 입력을 채널 ID로 변환."""
    raw = raw.strip()

    # 직접 채널 ID (UC로 시작하는 24자)
    if re.match(r'^UC[\w-]{22}$', raw):
        return raw

    # URL에서 채널 ID 추출
    m = re.search(r'youtube\.com/channel/(UC[\w-]{22})', raw)
    if m:
        return m.group(1)

    # @핸들 또는 /c/ /user/ URL → forHandle / forUsername API 조회
    handle = raw
    m2 = re.search(r'youtube\.com/@([\w.-]+)', raw)
    if m2:
        handle = '@' + m2.group(1)
    elif re.search(r'youtube\.com/(?:c|user)/([\w.-]+)', raw):
        m3 = re.search(r'youtube\.com/(?:c|user)/([\w.-]+)', raw)
        handle = m3.group(1) if m3 else raw

    # YouTube API 조회
    try:
        kwargs = {"part": "id,snippet", "maxResults": 1}
        if handle.startswith('@'):
            kwargs["forHandle"] = handle
        else:
            kwargs["forUsername"] = handle
        resp = youtube_client.get_client().channels().list(**kwargs).execute()
        items = resp.get("items", [])
        return items[0]["id"] if items else None
    except HttpError:
        return None


@app.post("/api/channels")
async def add_channel(req: ChannelAddRequest):
    """채널 추가: URL·@핸들·ID 모두 허용."""
    channel_id = _resolve_channel_id(req.input)
    if not channel_id:
        raise HTTPException(status_code=400, detail="채널을 찾을 수 없습니다. URL, @핸들, 또는 채널 ID를 확인해주세요.")

    # 채널 정보 조회
    try:
        resp = youtube_client.get_client().channels().list(
            part="snippet,statistics",
            id=channel_id,
            fields="items(id,snippet(title,thumbnails),statistics(subscriberCount))",
        ).execute()
        items = resp.get("items", [])
        if not items:
            raise HTTPException(status_code=404, detail="채널 정보를 가져올 수 없습니다.")
        snippet = items[0]["snippet"]
        stats   = items[0].get("statistics", {})
        title   = snippet.get("title", "")
        thumb   = snippet.get("thumbnails", {}).get("default", {}).get("url", "")
        subs    = int(stats.get("subscriberCount", 0))
    except HttpError as e:
        raise HTTPException(status_code=502, detail=f"YouTube API 오류: {e}")

    ok = await store.add_channel({
        "channel_id": channel_id,
        "title": title,
        "thumbnail_url": thumb,
        "subscriber_count": subs,
    })
    if not ok:
        raise HTTPException(status_code=409, detail="이미 등록된 채널입니다.")

    # 폴링 루프에 채널 추가 통지
    from src.scheduler import poller as p
    if channel_id not in p._runtime_channels:
        p._runtime_channels.add(channel_id)

    await broadcast({"type": "channel_added", "channel_id": channel_id, "title": title, "thumbnail_url": thumb, "subscriber_count": subs})
    logger.info("채널 추가: %s (%s)", title, channel_id)
    return {"channel_id": channel_id, "title": title, "thumbnail_url": thumb, "subscriber_count": subs}


@app.delete("/api/channels/{channel_id}")
async def remove_channel(channel_id: str):
    """채널 제거."""
    title = await store.remove_channel(channel_id)
    if title is None:
        raise HTTPException(status_code=404, detail="등록되지 않은 채널입니다.")

    from src.scheduler import poller as p
    p._runtime_channels.discard(channel_id)

    await broadcast({"type": "channel_removed", "channel_id": channel_id, "title": title})
    logger.info("채널 제거: %s (%s)", title, channel_id)
    return {"ok": True}


# ── 영상 직접 요약 API ─────────────────────────────────────

class SummarizeRequest(BaseModel):
    input: str  # YouTube URL 또는 영상 ID


def _extract_video_id(raw: str) -> str | None:
    """YouTube URL 또는 영상 ID에서 video_id 추출."""
    raw = raw.strip()
    # youtu.be/ID
    m = re.search(r'youtu\.be/([\w-]{11})', raw)
    if m:
        return m.group(1)
    # youtube.com/watch?v=ID
    m = re.search(r'[?&]v=([\w-]{11})', raw)
    if m:
        return m.group(1)
    # youtube.com/shorts/ID
    m = re.search(r'youtube\.com/shorts/([\w-]{11})', raw)
    if m:
        return m.group(1)
    # 11자리 영상 ID 직접 입력
    if re.match(r'^[\w-]{11}$', raw):
        return raw
    return None


@app.post("/api/summarize")
async def summarize_video_request(req: SummarizeRequest):
    """영상 URL 또는 ID를 받아 즉시 요약 파이프라인 실행."""
    video_id = _extract_video_id(req.input)
    if not video_id:
        raise HTTPException(status_code=400, detail="유효한 YouTube 영상 URL 또는 ID가 아닙니다.")

    # 영상 정보 조회
    try:
        resp = youtube_client.get_client().videos().list(
            part="snippet,statistics,contentDetails",
            id=video_id,
            fields="items(id,snippet(title,description,channelTitle,channelId,publishedAt,tags),statistics(viewCount,likeCount),contentDetails(duration))",
        ).execute()
        items = resp.get("items", [])
        if not items:
            raise HTTPException(status_code=404, detail="영상을 찾을 수 없습니다.")
    except HttpError as e:
        raise HTTPException(status_code=502, detail=f"YouTube API 오류: {e}")

    item = items[0]
    snippet = item["snippet"]
    stats = item.get("statistics", {})
    content = item.get("contentDetails", {})

    video = {
        "video_id": video_id,
        "channel_id": snippet.get("channelId", ""),
        "channel_title": snippet.get("channelTitle", ""),
        "title": snippet.get("title", ""),
        "description": snippet.get("description", "")[:3000],
        "published_at": snippet.get("publishedAt", ""),
        "thumbnail_url": f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg",
        "duration": content.get("duration", ""),
        "view_count": int(stats.get("viewCount", 0)),
        "like_count": int(stats.get("likeCount", 0)),
        "tags": snippet.get("tags", []),
    }

    # 즉시 감지 이벤트 브로드캐스트 후 백그라운드에서 요약
    await broadcast({"type": "video_detected", "video": video, "requested": True})

    from src.scheduler import poller as p
    asyncio.create_task(p._run_video_summary_pipeline(video))

    return {"ok": True, "video_id": video_id, "title": video["title"]}


static_dir = Path(__file__).parent.parent.parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
