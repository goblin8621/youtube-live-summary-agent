"""Claude API를 사용해 라이브 방송 내용을 요약합니다."""
import json
from src.pipeline import ai_client
from src.pipeline.preprocessor import split_into_chunks
from src.pipeline.noun_verifier import extract_and_verify, apply_verified_nouns
from src.utils.logger import get_logger

logger = get_logger(__name__)

_CHUNK_SYSTEM = """당신은 유튜브 라이브 방송 내용을 분석하는 전문 어시스턴트입니다.
주어진 방송 내용(자막 또는 채팅)의 일부를 분석해 핵심 내용을 간결하게 요약해주세요."""

_CHUNK_USER = """다음은 라이브 방송의 일부 내용입니다.

제목: {title}
채널: {channel}

--- 내용 ---
{content}

위 내용의 핵심 사항을 3-5줄로 요약해주세요. 중요한 발언, 발표, 이벤트를 중심으로 작성하세요."""

_FINAL_SYSTEM = """당신은 유튜브 라이브 방송 전체 내용을 종합 분석하는 전문 어시스턴트입니다.
응답은 반드시 유효한 JSON으로만 출력하세요."""

_FINAL_USER = """다음은 유튜브 라이브 방송의 전체 요약 정보입니다.

제목: {title}
채널: {channel}
방송 시간: {duration}
최대 동시 시청자: {peak_viewers:,}명

--- 검증된 고유명사 사전 (반드시 이 표기를 사용하세요) ---
{verified_nouns}

--- 주의사항 ---
{warnings}

--- 방송 내용 요약 ---
{summaries}

위 정보를 종합하여 다음 JSON 형식으로 출력해주세요.
고유명사는 반드시 위 사전의 공식 표기를 사용하세요:
{{
  "summary_text": "전체 방송 내용을 3-5문단으로 요약한 글 (마크다운 형식)",
  "key_topics": ["핵심 주제 1", "핵심 주제 2", "핵심 주제 3"],
  "highlights": [
    {{"timestamp": "HH:MM:SS 또는 null", "description": "주요 이벤트 설명"}},
    ...
  ],
  "one_liner": "방송 전체를 한 줄로 요약",
  "glossary": [
    {{"term": "용어", "description": "한 줄 설명"}}
  ]
}}"""


def _format_duration(seconds: int) -> str:
    h, m = divmod(seconds // 60, 60)
    s = seconds % 60
    return f"{h}시간 {m}분 {s}초" if h else f"{m}분 {s}초"


def _summarize_chunk(chunk: str, title: str, channel: str) -> str:
    return ai_client.chat(
        _CHUNK_SYSTEM,
        _CHUNK_USER.format(title=title, channel=channel, content=chunk),
        max_tokens=1024,
    )


def _summarize_final(chunk_summaries: list[str], session: dict,
                     noun_result: dict | None = None) -> dict:
    duration_str = _format_duration(session.get("duration_secs", 0))
    combined = "\n\n".join(
        f"[파트 {i+1}]\n{s}" for i, s in enumerate(chunk_summaries)
    )

    verified = (noun_result or {}).get("verified", {})
    warnings = (noun_result or {}).get("warnings", [])
    verified_str = "\n".join(f"  {k} → {v}" for k, v in verified.items()) or "없음"
    warnings_str = "\n".join(f"- {w}" for w in warnings) or "없음"

    raw = ai_client.chat(
        _FINAL_SYSTEM,
        _FINAL_USER.format(
            title=session.get("title", ""),
            channel=session.get("channel_title", ""),
            duration=duration_str,
            peak_viewers=session.get("peak_viewers", 0),
            verified_nouns=verified_str,
            warnings=warnings_str,
            summaries=combined,
        ),
        max_tokens=4096,
    ).strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    result = json.loads(raw)

    # noun_verifier의 glossary 병합 (중복 제거)
    existing_terms = {g["term"] for g in result.get("glossary", [])}
    for g in (noun_result or {}).get("glossary", []):
        if g["term"] not in existing_terms:
            result.setdefault("glossary", []).append({"term": g["term"], "description": g["description"]})

    result["noun_verification"] = {
        "verified_count": len(verified),
        "warnings": warnings,
    }
    return result


def summarize(caption_text: str, chat_text: str, session: dict) -> dict:
    """
    방송 내용을 Claude로 요약.
    Pass 1: 고유명사 추출·검증
    Pass 2: 검증된 표기로 치환 후 map-reduce 요약
    """
    content = caption_text if caption_text.strip() else chat_text
    source = "자막" if caption_text.strip() else "채팅"
    logger.info("요약 소스: %s (%d자)", source, len(content))

    if not content.strip():
        logger.warning("요약할 내용 없음 (session=%s)", session.get("id"))
        return {
            "summary_text": "방송 내용을 수집하지 못했습니다.",
            "key_topics": [], "highlights": [], "one_liner": "내용 없음",
            "glossary": [], "noun_verification": {"verified_count": 0, "warnings": []},
        }

    # Pass 1: 고유명사 검증
    logger.info("고유명사 검증 중...")
    noun_result = extract_and_verify(
        content,
        title=session.get("title", ""),
        channel=session.get("channel_title", ""),
        source=source,
    )

    # 검증된 표기로 텍스트 치환
    clean_content = apply_verified_nouns(content, noun_result.get("verified", {}))

    # Pass 2: 요약
    chunks = split_into_chunks(clean_content)
    title = session.get("title", "")
    channel = session.get("channel_title", "")

    if len(chunks) == 1:
        logger.info("단일 청크 요약 진행")
        chunk_summaries = [_summarize_chunk(chunks[0], title, channel)]
    else:
        logger.info("다중 청크 map 요약 (%d개)", len(chunks))
        chunk_summaries = []
        for i, chunk in enumerate(chunks):
            logger.info("청크 %d/%d 요약 중...", i + 1, len(chunks))
            chunk_summaries.append(_summarize_chunk(chunk, title, channel))

    logger.info("최종 통합 요약 생성 중...")
    result = _summarize_final(chunk_summaries, session, noun_result)
    logger.info("요약 완료: %s", result.get("one_liner", ""))
    return result
