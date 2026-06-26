"""
채널의 라이브 방송 시작/종료를 감지합니다.
YouTube Data API units: channels.list = 1유닛 (search.list 100유닛 대비 절약)
"""
from datetime import datetime, timezone
from googleapiclient.errors import HttpError
from tenacity import retry, stop_after_attempt, wait_exponential
from src.watcher import youtube_client
from src.utils.logger import get_logger

logger = get_logger(__name__)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _fetch_channel_live_status(channel_id: str) -> dict | None:
    """
    channels.list로 채널의 현재 라이브 스트림 ID를 1유닛으로 확인.
    반환: {"video_id": ..., "title": ..., "concurrent_viewers": ...} or None
    """
    yt = youtube_client.get_client()
    resp = yt.channels().list(
        part="snippet,statistics",
        id=channel_id,
        fields="items(id,snippet(title),statistics(videoCount))",
    ).execute()

    if not resp.get("items"):
        return None

    channel_title = resp["items"][0]["snippet"]["title"]

    live_resp = yt.search().list(
        part="snippet",
        channelId=channel_id,
        eventType="live",
        type="video",
        maxResults=1,
        fields="items(id(videoId),snippet(title,liveBroadcastContent))",
    ).execute()

    items = live_resp.get("items", [])
    if not items:
        return None

    item = items[0]
    video_id = item["id"]["videoId"]

    video_resp = yt.videos().list(
        part="liveStreamingDetails,snippet",
        id=video_id,
        fields="items(snippet(title,channelTitle),liveStreamingDetails(concurrentViewers,actualStartTime))",
    ).execute()

    v_items = video_resp.get("items", [])
    if not v_items:
        return None

    details = v_items[0].get("liveStreamingDetails", {})
    snippet = v_items[0].get("snippet", {})

    return {
        "video_id": video_id,
        "channel_id": channel_id,
        "channel_title": channel_title,
        "title": snippet.get("title", ""),
        "concurrent_viewers": int(details.get("concurrentViewers", 0)),
        "actual_start_time": details.get("actualStartTime", datetime.now(timezone.utc).isoformat()),
    }


def check_channel_live(channel_id: str) -> dict | None:
    try:
        return _fetch_channel_live_status(channel_id)
    except HttpError as e:
        if e.resp.status == 403:
            logger.error("YouTube API 쿼터 초과 또는 권한 오류: %s", e)
        else:
            logger.warning("YouTube API 오류 (channel=%s): %s", channel_id, e)
        return None
    except Exception as e:
        logger.error("라이브 상태 확인 실패 (channel=%s): %s", channel_id, e)
        return None
