"""채팅·자막 텍스트를 Claude에 넘기기 전 전처리합니다."""
import re
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Claude claude-sonnet-4-6 context: 200k tokens. 안전 마진으로 150k 토큰 기준 약 600,000자.
MAX_CHARS_PER_CHUNK = 80_000  # 청크당 ~20k 토큰 (넉넉한 마진)


def _clean_text(text: str) -> str:
    text = re.sub(r"http\S+", "[링크]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def build_caption_text(captions: list[dict]) -> str:
    """자막을 타임스탬프 포함 텍스트로 변환."""
    lines = []
    for c in captions:
        mins, secs = divmod(int(c["start_sec"]), 60)
        hours, mins = divmod(mins, 60)
        ts = f"{hours:02d}:{mins:02d}:{secs:02d}" if hours else f"{mins:02d}:{secs:02d}"
        lines.append(f"[{ts}] {_clean_text(c['text'])}")
    return "\n".join(lines)


def build_chat_text(messages: list[dict], sample_ratio: float = 1.0) -> str:
    """채팅 메시지를 텍스트로 변환. 메시지 수가 많으면 샘플링."""
    if not messages:
        return ""
    if len(messages) > 2000:
        step = max(1, int(len(messages) / 2000 / sample_ratio))
        messages = messages[::step]
        logger.info("채팅 샘플링 적용: %d개 → %d개", len(messages) * step, len(messages))

    lines = []
    for m in messages:
        author = m["author"][:20] if m["author"] else "익명"
        msg = _clean_text(m["message"])
        if msg:
            lines.append(f"{author}: {msg}")
    return "\n".join(lines)


def split_into_chunks(text: str, max_chars: int = MAX_CHARS_PER_CHUNK) -> list[str]:
    """텍스트를 라인 경계 기준으로 청크 분할."""
    if len(text) <= max_chars:
        return [text]

    chunks = []
    lines = text.split("\n")
    current = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1
        if current_len + line_len > max_chars and current:
            chunks.append("\n".join(current))
            current = [line]
            current_len = line_len
        else:
            current.append(line)
            current_len += line_len

    if current:
        chunks.append("\n".join(current))

    logger.info("텍스트 청크 분할: %d개", len(chunks))
    return chunks
