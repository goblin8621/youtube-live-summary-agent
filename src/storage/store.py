"""스토리지 추상화 레이어.

DB 파일이 존재하면 DB 모드, 없으면 파일 모드로 동작합니다.
- DB 모드  : 설정 → app_settings 테이블 / 요약 → summaries/video_summaries 테이블
- 파일 모드 : 설정 → data/config.json   / 요약 → data/summaries/{channel}/{date}/
"""
from pathlib import Path
from src.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

_use_db: bool = True


def init(use_db: bool):
    global _use_db
    _use_db = use_db
    mode = "DB" if use_db else "파일"
    logger.info("스토리지 모드: %s", mode)


def is_db_mode() -> bool:
    return _use_db


# ── 설정 ──────────────────────────────────────────────────────

async def get_setting(key: str) -> str:
    if _use_db:
        from src.storage import database as db
        return (await db.get_setting(key)) or ""
    else:
        section, _, k = key.partition(".")
        from src.storage import config_store
        return config_store.get(section, k)


async def set_setting(key: str, value: str):
    if _use_db:
        from src.storage import database as db
        await db.set_setting(key, value)
    else:
        section, _, k = key.partition(".")
        from src.storage import config_store
        config_store.save(section, k, value)


async def set_settings_many(updates: dict[str, dict[str, str]]):
    """{'ai': {'provider': ..., 'model': ...}, 'youtube': {'api_key': ...}} 형태로 일괄 저장."""
    if _use_db:
        from src.storage import database as db
        for section, kv in updates.items():
            for k, v in kv.items():
                await db.set_setting(f"{section}.{k}", v)
    else:
        from src.storage import config_store
        config_store.save_many(updates)


# ── 요약 저장 ─────────────────────────────────────────────────

async def save_summary(session_id: str, session: dict, summary: dict):
    if _use_db:
        from src.storage import database as db
        await db.save_summary(session_id, summary)
    else:
        import asyncio
        loop = asyncio.get_event_loop()
        from src.storage import summary_store
        await loop.run_in_executor(None, summary_store.save_live_summary, session, summary)


async def save_video_summary(video: dict, summary: dict):
    if _use_db:
        from src.storage import database as db
        await db.save_video_summary(video, summary)
    else:
        import asyncio
        loop = asyncio.get_event_loop()
        from src.storage import summary_store
        await loop.run_in_executor(None, summary_store.save_video_summary, video, summary)


# ── 히스토리 조회 ─────────────────────────────────────────────

async def get_history(limit: int = 50) -> list[dict]:
    if _use_db:
        import aiosqlite
        async with aiosqlite.connect(settings.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT s.*, sm.summary_text, sm.key_topics, sm.highlights, sm.one_liner
                FROM live_sessions s
                LEFT JOIN summaries sm ON s.id = sm.session_id
                ORDER BY s.started_at DESC
                LIMIT ?
            """, (limit,)) as cur:
                return [dict(r) for r in await cur.fetchall()]
    else:
        import asyncio
        from src.storage import summary_store
        return await asyncio.get_event_loop().run_in_executor(
            None, summary_store.load_history, limit
        )
