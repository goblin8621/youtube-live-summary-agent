import aiosqlite
import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from src.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


async def init_db():
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(settings.db_path) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS live_sessions (
                id              TEXT PRIMARY KEY,
                channel_id      TEXT NOT NULL,
                channel_title   TEXT,
                video_id        TEXT NOT NULL,
                title           TEXT,
                started_at      TEXT,
                ended_at        TEXT,
                status          TEXT DEFAULT 'live',
                peak_viewers    INTEGER DEFAULT 0,
                duration_secs   INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id              TEXT PRIMARY KEY,
                session_id      TEXT NOT NULL,
                author          TEXT,
                message         TEXT,
                published_at    TEXT,
                FOREIGN KEY (session_id) REFERENCES live_sessions(id)
            );

            CREATE TABLE IF NOT EXISTS captions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id      TEXT NOT NULL,
                start_sec       REAL,
                text            TEXT,
                FOREIGN KEY (session_id) REFERENCES live_sessions(id)
            );

            CREATE TABLE IF NOT EXISTS summaries (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id      TEXT NOT NULL UNIQUE,
                summary_text    TEXT,
                key_topics      TEXT,
                highlights      TEXT,
                created_at      TEXT,
                FOREIGN KEY (session_id) REFERENCES live_sessions(id)
            );

            CREATE TABLE IF NOT EXISTS monitored_channels (
                channel_id      TEXT PRIMARY KEY,
                title           TEXT NOT NULL,
                thumbnail_url   TEXT,
                subscriber_count INTEGER DEFAULT 0,
                added_at        TEXT DEFAULT (datetime('now')),
                last_video_id   TEXT
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key        TEXT PRIMARY KEY,
                value      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS video_summaries (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id        TEXT NOT NULL UNIQUE,
                channel_id      TEXT NOT NULL,
                channel_title   TEXT,
                title           TEXT,
                description     TEXT,
                published_at    TEXT,
                thumbnail_url   TEXT,
                duration        TEXT,
                view_count      INTEGER DEFAULT 0,
                like_count      INTEGER DEFAULT 0,
                one_liner       TEXT,
                summary_text    TEXT,
                key_topics      TEXT,
                target_audience TEXT,
                highlights      TEXT,
                sentiment       TEXT,
                created_at      TEXT DEFAULT (datetime('now'))
            );
        """)
        await db.commit()
    logger.info("DB initialized: %s", settings.db_path)


async def upsert_session(session: dict):
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute("""
            INSERT INTO live_sessions
                (id, channel_id, channel_title, video_id, title, started_at, status, peak_viewers)
            VALUES (:id, :channel_id, :channel_title, :video_id, :title, :started_at, :status, :peak_viewers)
            ON CONFLICT(id) DO UPDATE SET
                status       = excluded.status,
                peak_viewers = MAX(live_sessions.peak_viewers, excluded.peak_viewers),
                title        = excluded.title
        """, session)
        await db.commit()


async def close_session(session_id: str, ended_at: str, duration_secs: int):
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute("""
            UPDATE live_sessions
            SET status = 'ended', ended_at = ?, duration_secs = ?
            WHERE id = ?
        """, (ended_at, duration_secs, session_id))
        await db.commit()


async def insert_chat_messages(messages: list[dict]):
    if not messages:
        return
    async with aiosqlite.connect(settings.db_path) as db:
        await db.executemany("""
            INSERT OR IGNORE INTO chat_messages (id, session_id, author, message, published_at)
            VALUES (:id, :session_id, :author, :message, :published_at)
        """, messages)
        await db.commit()


async def insert_captions(session_id: str, captions: list[dict]):
    if not captions:
        return
    async with aiosqlite.connect(settings.db_path) as db:
        await db.executemany("""
            INSERT INTO captions (session_id, start_sec, text)
            VALUES (?, ?, ?)
        """, [(session_id, c["start"], c["text"]) for c in captions])
        await db.commit()


async def save_summary(session_id: str, summary: dict):
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute("""
            INSERT OR REPLACE INTO summaries
                (session_id, summary_text, key_topics, highlights, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            session_id,
            summary["summary_text"],
            json.dumps(summary.get("key_topics", []), ensure_ascii=False),
            json.dumps(summary.get("highlights", []), ensure_ascii=False),
            datetime.utcnow().isoformat(),
        ))
        await db.commit()


async def get_session(session_id: str) -> Optional[dict]:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM live_sessions WHERE id = ?", (session_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_chat_messages(session_id: str) -> list[dict]:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT author, message, published_at FROM chat_messages WHERE session_id = ? ORDER BY published_at",
            (session_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_captions(session_id: str) -> list[dict]:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT start_sec, text FROM captions WHERE session_id = ? ORDER BY start_sec",
            (session_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_live_session_ids() -> list[str]:
    async with aiosqlite.connect(settings.db_path) as db:
        async with db.execute(
            "SELECT id FROM live_sessions WHERE status = 'live'"
        ) as cur:
            rows = await cur.fetchall()
            return [r[0] for r in rows]


# ── 영상 추적 ────────────────────────────────────────────────

async def get_last_video_id(channel_id: str) -> str | None:
    async with aiosqlite.connect(settings.db_path) as db:
        async with db.execute(
            "SELECT last_video_id FROM monitored_channels WHERE channel_id = ?",
            (channel_id,),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def set_last_video_id(channel_id: str, video_id: str):
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            "UPDATE monitored_channels SET last_video_id = ? WHERE channel_id = ?",
            (video_id, channel_id),
        )
        await db.commit()


async def save_video_summary(video: dict, summary: dict):
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute("""
            INSERT OR REPLACE INTO video_summaries
                (video_id, channel_id, channel_title, title, description,
                 published_at, thumbnail_url, duration, view_count, like_count,
                 one_liner, summary_text, key_topics, target_audience, highlights, sentiment)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            video["video_id"],
            video["channel_id"],
            video.get("channel_title", ""),
            video.get("title", ""),
            video.get("description", "")[:2000],
            video.get("published_at", ""),
            video.get("thumbnail_url", ""),
            video.get("duration", ""),
            video.get("view_count", 0),
            video.get("like_count", 0),
            summary.get("one_liner", ""),
            summary.get("summary_text", ""),
            json.dumps(summary.get("key_topics", []), ensure_ascii=False),
            summary.get("target_audience", ""),
            json.dumps(summary.get("highlights", []), ensure_ascii=False),
            summary.get("sentiment", "neutral"),
        ))
        await db.commit()


async def get_setting(key: str) -> str | None:
    async with aiosqlite.connect(settings.db_path) as db:
        async with db.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
            (key, value),
        )
        await db.commit()


async def get_video_summaries(limit: int = 30) -> list[dict]:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM video_summaries ORDER BY published_at DESC LIMIT ?", (limit,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]
