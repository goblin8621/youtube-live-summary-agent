"""방송 종료 후 자동 생성 자막을 가져옵니다."""
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from src.utils.logger import get_logger

logger = get_logger(__name__)


def fetch_captions(video_id: str) -> list[dict]:
    """
    자동 생성 자막 우선 → 한국어 → 영어 순으로 시도.
    반환: [{"start": float, "text": str}, ...]
    """
    priority = ["ko", "en", "en-US", "en-GB"]
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        # 자동 생성 자막 우선
        for lang in priority:
            try:
                t = transcript_list.find_generated_transcript([lang])
                data = t.fetch()
                logger.info("자동 생성 자막 수집 완료 (lang=%s, %d segments)", lang, len(data))
                return [{"start": seg.start, "text": seg.text} for seg in data]
            except Exception:
                pass

        # 수동 자막
        for lang in priority:
            try:
                t = transcript_list.find_transcript([lang])
                data = t.fetch()
                logger.info("수동 자막 수집 완료 (lang=%s, %d segments)", lang, len(data))
                return [{"start": seg.start, "text": seg.text} for seg in data]
            except Exception:
                pass

        logger.warning("자막 없음 (video=%s) - 채팅 로그만으로 요약 진행", video_id)
        return []

    except TranscriptsDisabled:
        logger.warning("자막 비활성화 (video=%s)", video_id)
        return []
    except NoTranscriptFound:
        logger.warning("사용 가능한 자막 없음 (video=%s)", video_id)
        return []
    except Exception as e:
        logger.error("자막 수집 오류 (video=%s): %s", video_id, e)
        return []
