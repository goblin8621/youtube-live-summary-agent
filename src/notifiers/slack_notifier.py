"""Slack으로 요약 리포트를 전송합니다."""
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from src.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

_client = WebClient(token=settings.slack_bot_token) if settings.slack_enabled else None


def send_summary(session: dict, summary: dict, report_md: str):
    if not _client:
        return

    title = session.get("title", "제목 없음")
    channel = session.get("channel_title", "")
    video_id = session.get("video_id", "")
    peak = session.get("peak_viewers", 0)
    one_liner = summary.get("one_liner", "")
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    topics = ", ".join(summary.get("key_topics", [])[:5])

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"📺 라이브 방송 종료: {title}"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*채널*\n{channel}"},
                {"type": "mrkdwn", "text": f"*최대 시청자*\n{peak:,}명"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*한줄 요약*\n{one_liner}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*핵심 주제*\n{topics or '없음'}"},
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "영상 보러가기"},
                    "url": video_url,
                    "style": "primary",
                }
            ],
        },
        {"type": "divider"},
    ]

    try:
        _client.chat_postMessage(
            channel=settings.slack_channel_id,
            text=f"라이브 방송 종료: {title}",
            blocks=blocks,
        )

        # 전체 리포트는 스레드에 전송 (길이 제한 회피)
        snippets = report_md[:2900]
        _client.chat_postMessage(
            channel=settings.slack_channel_id,
            text=f"```{snippets}```",
            thread_ts=None,
        )
        logger.info("Slack 전송 완료 (channel=%s)", settings.slack_channel_id)
    except SlackApiError as e:
        logger.error("Slack 전송 실패: %s", e.response["error"])
