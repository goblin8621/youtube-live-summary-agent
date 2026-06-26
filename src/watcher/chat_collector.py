"""방송 중 라이브 채팅을 주기적으로 수집합니다."""
from googleapiclient.errors import HttpError
from tenacity import retry, stop_after_attempt, wait_exponential
from src.watcher import youtube_client
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _get_live_chat_id(video_id: str) -> str | None:
    try:
        resp = youtube_client.get_client().videos().list(
            part="liveStreamingDetails",
            id=video_id,
            fields="items(liveStreamingDetails(activeLiveChatId))",
        ).execute()
        items = resp.get("items", [])
        if not items:
            return None
        return items[0].get("liveStreamingDetails", {}).get("activeLiveChatId")
    except Exception as e:
        logger.warning("liveChatId 조회 실패 (video=%s): %s", video_id, e)
        return None


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5))
def _fetch_chat_page(live_chat_id: str, page_token: str | None) -> dict:
    kwargs = dict(
        liveChatId=live_chat_id,
        part="snippet,authorDetails",
        maxResults=200,
        fields="nextPageToken,pollingIntervalMillis,items(id,snippet(displayMessage,publishedAt),authorDetails(displayName))",
    )
    if page_token:
        kwargs["pageToken"] = page_token
    return youtube_client.get_client().liveChatMessages().list(**kwargs).execute()


class ChatCollector:
    def __init__(self, video_id: str, session_id: str):
        self.video_id = video_id
        self.session_id = session_id
        self._live_chat_id: str | None = None
        self._next_page_token: str | None = None

    def init(self) -> bool:
        self._live_chat_id = _get_live_chat_id(self.video_id)
        if not self._live_chat_id:
            logger.warning("라이브 채팅 없음 (video=%s)", self.video_id)
            return False
        logger.info("채팅 수집 시작 (chatId=%s)", self._live_chat_id)
        return True

    def collect_page(self) -> list[dict]:
        if not self._live_chat_id:
            return []
        try:
            resp = _fetch_chat_page(self._live_chat_id, self._next_page_token)
            self._next_page_token = resp.get("nextPageToken")

            messages = []
            for item in resp.get("items", []):
                snippet = item.get("snippet", {})
                author = item.get("authorDetails", {})
                messages.append({
                    "id": item["id"],
                    "session_id": self.session_id,
                    "author": author.get("displayName", ""),
                    "message": snippet.get("displayMessage", ""),
                    "published_at": snippet.get("publishedAt", ""),
                })
            return messages
        except HttpError as e:
            if e.resp.status == 403:
                logger.warning("채팅 수집 중 채팅 비활성화 또는 쿼터 초과: %s", e)
            else:
                logger.warning("채팅 수집 오류: %s", e)
            return []
