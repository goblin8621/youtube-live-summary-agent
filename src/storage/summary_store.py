"""파일 기반 요약 저장소. DB 없을 때 사용.

구조: data/summaries/{channel_id}/{YYYY-MM-DD}/{session_id|video_{id}}.json
"""
import json
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from src.utils.logger import get_logger

logger = get_logger(__name__)

_BASE = Path("./data/summaries")
_RETENTION_DAYS = 10


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def save_live_summary(session: dict, summary: dict):
    channel_id = session.get("channel_id", "unknown")
    session_id = session.get("id", "unknown")
    d = _BASE / channel_id / _today()
    d.mkdir(parents=True, exist_ok=True)
    payload = {
        "type": "live",
        "session": session,
        "summary": summary,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    (d / f"{session_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("요약 파일 저장: %s/%s", channel_id, _today())


def save_video_summary(video: dict, summary: dict):
    channel_id = video.get("channel_id", "unknown")
    video_id = video.get("video_id", "unknown")
    date = (video.get("published_at") or _today())[:10]
    d = _BASE / channel_id / date
    d.mkdir(parents=True, exist_ok=True)
    payload = {
        "type": "video",
        "video": video,
        "summary": summary,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    (d / f"video_{video_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("영상 요약 파일 저장: %s/%s", channel_id, date)


def load_history(limit: int = 50) -> list[dict]:
    if not _BASE.exists():
        return []
    files = sorted(_BASE.rglob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    results = []
    for f in files[:limit]:
        try:
            results.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return results


def cleanup_old_summaries():
    if not _BASE.exists():
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=_RETENTION_DAYS)
    deleted = 0
    for ch_dir in _BASE.iterdir():
        if not ch_dir.is_dir():
            continue
        for date_dir in list(ch_dir.iterdir()):
            if not date_dir.is_dir():
                continue
            try:
                dir_date = datetime.strptime(date_dir.name, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if dir_date < cutoff:
                    shutil.rmtree(date_dir)
                    deleted += 1
            except ValueError:
                pass
        if not any(ch_dir.iterdir()):
            ch_dir.rmdir()
    if deleted:
        logger.info("오래된 요약 정리: %d개 폴더 삭제 (%d일 이상)", deleted, _RETENTION_DAYS)
