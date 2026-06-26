"""Claude API로 업로드 영상을 요약합니다 (라이브와 별도 프롬프트)."""
import json
import re
from src.pipeline import ai_client
from src.pipeline.preprocessor import split_into_chunks
from src.pipeline.noun_verifier import extract_and_verify, apply_verified_nouns
from src.utils.logger import get_logger

logger = get_logger(__name__)

_SYSTEM = """당신은 유튜브 영상 내용을 분석하는 전문 어시스턴트입니다.
응답은 반드시 유효한 JSON으로만 출력하세요."""

_PROMPT = """다음은 유튜브 영상 정보입니다.

제목: {title}
채널: {channel}
게시일: {published}
길이: {duration}
조회수: {views:,}  좋아요: {likes:,}
태그: {tags}

--- 영상 설명 ---
{description}

--- 검증된 고유명사 사전 (반드시 이 표기를 사용하세요) ---
{verified_nouns}

--- 주의사항 ---
{warnings}

--- 자막 (있는 경우) ---
{transcript}

위 정보를 종합해 다음 JSON으로 출력하세요.
고유명사는 반드시 위 사전의 공식 표기를 사용하세요:
{{
  "one_liner": "영상을 한 문장으로 요약",
  "summary_text": "영상 내용을 2-4문단으로 요약 (마크다운)",
  "key_topics": ["핵심 주제 1", "핵심 주제 2", ...],
  "target_audience": "이 영상이 유용한 대상 (예: 입문자, 실무 개발자 등)",
  "highlights": [
    {{"timestamp": "MM:SS 또는 null", "description": "주요 섹션 설명"}},
    ...
  ],
  "glossary": [
    {{"term": "용어", "description": "한 줄 설명"}}
  ],
  "sentiment": "positive | neutral | negative",
  "recommended": true
}}"""


def _parse_iso_duration(iso: str) -> str:
    """PT1H30M45S → 1시간 30분 45초"""
    m = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', iso or '')
    if not m:
        return iso
    h, mn, s = m.group(1), m.group(2), m.group(3)
    parts = []
    if h:  parts.append(f"{h}시간")
    if mn: parts.append(f"{mn}분")
    if s:  parts.append(f"{s}초")
    return " ".join(parts) or "알 수 없음"


def summarize_video(video: dict, captions: list[dict]) -> dict:
    """
    업로드 영상 요약.
    Pass 1: 고유명사 추출·검증
    Pass 2: 검증된 표기로 치환 후 요약
    """
    from src.pipeline.preprocessor import build_caption_text

    caption_text = build_caption_text(captions) if captions else ""
    description = video.get("description", "")
    tags = ", ".join(video.get("tags", [])[:15]) or "없음"
    duration_str = _parse_iso_duration(video.get("duration", ""))
    title = video.get("title", "")
    channel = video.get("channel_title", "")

    # Pass 1: 고유명사 검증 (자막 우선, 없으면 설명 사용)
    raw_content = caption_text or description
    logger.info("고유명사 검증 중: %s", title)
    noun_result = extract_and_verify(
        raw_content,
        title=title,
        channel=channel,
        source="자막" if caption_text else "영상설명",
    )

    # 검증된 표기로 치환
    clean_caption = apply_verified_nouns(caption_text, noun_result.get("verified", {}))
    clean_desc = apply_verified_nouns(description, noun_result.get("verified", {}))

    verified_str = "\n".join(f"  {k} → {v}" for k, v in noun_result.get("verified", {}).items()) or "없음"
    warnings_str = "\n".join(f"- {w}" for w in noun_result.get("warnings", [])) or "없음"

    # Pass 2: 요약
    content = clean_caption or clean_desc
    chunks = split_into_chunks(content) if content else [""]

    if len(chunks) == 1:
        transcript_part = chunks[0][:60_000]
    else:
        logger.info("영상 자막 청크 분할 (%d개)", len(chunks))
        from src.pipeline.summarizer import _summarize_chunk
        interim = [_summarize_chunk(c, title, channel) for c in chunks]
        transcript_part = "\n\n".join(f"[파트{i+1}] {s}" for i, s in enumerate(interim))

    prompt = _PROMPT.format(
        title=title,
        channel=channel,
        published=video.get("published_at", "")[:10],
        duration=duration_str,
        views=video.get("view_count", 0),
        likes=video.get("like_count", 0),
        tags=tags,
        verified_nouns=verified_str,
        warnings=warnings_str,
        description=clean_desc[:2000],
        transcript=transcript_part or "(자막 없음 — 영상 설명 기반으로 요약)",
    )

    logger.info("영상 요약 중: %s", title)
    raw = ai_client.chat(_SYSTEM, prompt, max_tokens=3000).strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    result = json.loads(raw)

    # noun_verifier glossary 병합
    existing = {g["term"] for g in result.get("glossary", [])}
    for g in noun_result.get("glossary", []):
        if g["term"] not in existing:
            result.setdefault("glossary", []).append({"term": g["term"], "description": g["description"]})

    result["noun_verification"] = {
        "verified_count": len(noun_result.get("verified", {})),
        "warnings": noun_result.get("warnings", []),
    }
    logger.info("영상 요약 완료: %s (고유명사 %d개 검증)",
                result.get("one_liner", ""), result["noun_verification"]["verified_count"])
    return result
