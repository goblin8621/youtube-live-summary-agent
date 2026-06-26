"""Notion 데이터베이스에 요약 리포트를 저장합니다."""
from notion_client import Client
from src.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

_notion = Client(auth=settings.notion_token) if settings.notion_enabled else None


def save_to_notion(session: dict, summary: dict, report_md: str):
    if not _notion:
        return

    title = session.get("title", "제목 없음")
    channel = session.get("channel_title", "")
    video_id = session.get("video_id", "")
    peak = session.get("peak_viewers", 0)
    started = session.get("started_at", "")
    ended = session.get("ended_at", "")
    one_liner = summary.get("one_liner", "")
    topics = summary.get("key_topics", [])
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    props = {
        "Name": {"title": [{"text": {"content": title}}]},
        "채널": {"rich_text": [{"text": {"content": channel}}]},
        "한줄 요약": {"rich_text": [{"text": {"content": one_liner[:2000]}}]},
        "영상 링크": {"url": video_url},
        "최대 시청자": {"number": peak},
        "핵심 주제": {"multi_select": [{"name": t[:100]} for t in topics[:5]]},
    }
    if started:
        props["시작 시각"] = {"date": {"start": started}}
    if ended:
        props["종료 시각"] = {"date": {"start": ended}}

    # 리포트 본문을 paragraph 블록으로 분할 (Notion API 2000자 제한)
    content_blocks = []
    for chunk in _split_md(report_md, 1900):
        content_blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]},
        })

    try:
        _notion.pages.create(
            parent={"database_id": settings.notion_database_id},
            properties=props,
            children=content_blocks[:100],  # Notion API 블록 수 제한
        )
        logger.info("Notion 저장 완료 (title=%s)", title)
    except Exception as e:
        logger.error("Notion 저장 실패: %s", e)


def _split_md(text: str, size: int) -> list[str]:
    return [text[i: i + size] for i in range(0, len(text), size)]
