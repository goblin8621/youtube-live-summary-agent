"""
채널의 신규 업로드 영상을 감지합니다.
uploads 플레이리스트 방식 사용 → search.list(100유닛) 대신
channels.list(1유닛) + playlistItems.list(1유닛)으로 처리.
"""
from googleapiclient.errors import HttpError
from tenacity import retry, stop_after_attempt, wait_exponential
from src.watcher import youtube_client
from src.utils.logger import get_logger

logger = get_logger(__name__)

# 채널별 uploads 플레이리스트 ID 캐시 (세션 내 재사용)
_uploads_playlist_cache: dict[str, str] = {}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
def _get_uploads_playlist_id(channel_id: str) -> str | None:
    if channel_id in _uploads_playlist_cache:
        return _uploads_playlist_cache[channel_id]
    resp = youtube_client.get_client().channels().list(
        part="contentDetails",
        id=channel_id,
        fields="items(contentDetails(relatedPlaylists(uploads)))",
    ).execute()
    items = resp.get("items", [])
    if not items:
        return None
    pl_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    _uploads_playlist_cache[channel_id] = pl_id
    return pl_id


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
def _fetch_latest_videos(playlist_id: str, max_results: int = 5) -> list[dict]:
    resp = youtube_client.get_client().playlistItems().list(
        part="snippet,contentDetails",
        playlistId=playlist_id,
        maxResults=max_results,
        fields="items(snippet(title,description,publishedAt,channelTitle,channelId,thumbnails),contentDetails(videoId))",
    ).execute()
    return resp.get("items", [])


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5))
def _fetch_video_details(video_ids: list[str]) -> list[dict]:
    resp = youtube_client.get_client().videos().list(
        part="snippet,statistics,contentDetails",
        id=",".join(video_ids),
        fields="items(id,snippet(title,description,channelTitle,channelId,publishedAt,tags,categoryId),statistics(viewCount,likeCount,commentCount),contentDetails(duration))",
    ).execute()
    return resp.get("items", [])


def get_new_videos(channel_id: str, since_video_id: str | None) -> list[dict]:
    """
    channel_id 채널에서 since_video_id 이후 업로드된 신규 영상 목록 반환.
    since_video_id=None 이면 최신 1개만 반환 (초기화용).
    반환: [{"video_id", "title", "description", "published_at", "channel_title",
            "thumbnail_url", "duration", "view_count", "like_count"}]
    """
    try:
        pl_id = _get_uploads_playlist_id(channel_id)
        if not pl_id:
            return []

        items = _fetch_latest_videos(pl_id, max_results=10)
        if not items:
            return []

        # since_video_id가 없으면 초기화 — 최신 1개 ID만 저장하고 요약 안 함
        if since_video_id is None:
            return []

        # since_video_id 이전까지만 수집 (최신순이므로 앞에서부터 slice)
        new_items = []
        for item in items:
            vid = item["contentDetails"]["videoId"]
            if vid == since_video_id:
                break
            new_items.append(item)

        if not new_items:
            return []

        # 상세 정보 추가 조회
        video_ids = [i["contentDetails"]["videoId"] for i in new_items]
        details_map = {v["id"]: v for v in _fetch_video_details(video_ids)}

        results = []
        for item in new_items:
            vid = item["contentDetails"]["videoId"]
            snippet = item["snippet"]
            detail = details_map.get(vid, {})
            d_snippet = detail.get("snippet", {})
            d_stats = detail.get("statistics", {})
            d_content = detail.get("contentDetails", {})
            thumb = (snippet.get("thumbnails", {}).get("high")
                     or snippet.get("thumbnails", {}).get("default")
                     or {}).get("url", "")
            results.append({
                "video_id": vid,
                "channel_id": channel_id,
                "channel_title": snippet.get("channelTitle", ""),
                "title": snippet.get("title", ""),
                "description": (d_snippet.get("description") or snippet.get("description", ""))[:3000],
                "published_at": snippet.get("publishedAt", ""),
                "thumbnail_url": thumb,
                "duration": d_content.get("duration", ""),  # ISO 8601 e.g. PT1H30M
                "view_count": int(d_stats.get("viewCount", 0)),
                "like_count": int(d_stats.get("likeCount", 0)),
                "tags": d_snippet.get("tags", []),
            })
        return results

    except HttpError as e:
        logger.warning("신규 영상 감지 오류 (channel=%s): %s", channel_id, e)
        return []
    except Exception as e:
        logger.error("신규 영상 감지 실패 (channel=%s): %s", channel_id, e)
        return []


def get_latest_video_id(channel_id: str) -> str | None:
    """채널의 가장 최신 영상 ID 반환 (초기 기준점 설정용)."""
    try:
        pl_id = _get_uploads_playlist_id(channel_id)
        if not pl_id:
            return None
        items = _fetch_latest_videos(pl_id, max_results=1)
        if not items:
            return None
        return items[0]["contentDetails"]["videoId"]
    except Exception as e:
        logger.warning("최신 영상 ID 조회 실패 (channel=%s): %s", channel_id, e)
        return None
