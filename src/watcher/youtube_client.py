"""
런타임에 YouTube API 키를 교체할 수 있는 클라이언트 팩토리.
UI 설정 키 > .env 키 순으로 사용.
키가 바뀔 때만 클라이언트를 재생성한다.
"""
from src.utils.logger import get_logger

logger = get_logger(__name__)

_runtime_key: str = ""
_cached_client = None
_cached_key: str = ""


def set_key(key: str):
    global _runtime_key, _cached_client
    _runtime_key = key
    _cached_client = None  # 다음 get_client() 호출 시 재생성
    logger.info("YouTube API 키 갱신")


def get_key() -> str:
    from src.config import settings
    return _runtime_key or settings.youtube_api_key


def get_client():
    """현재 키로 YouTube Data API v3 클라이언트 반환 (키 변경 시 재생성)."""
    global _cached_client, _cached_key
    key = get_key()
    if _cached_client is None or key != _cached_key:
        from googleapiclient.discovery import build
        _cached_client = build("youtube", "v3", developerKey=key)
        _cached_key = key
    return _cached_client
