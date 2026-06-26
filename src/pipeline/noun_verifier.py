"""
고유명사 추출·검색·검증 파이프라인.

Pass 1 — 추출  : Claude가 원본 텍스트에서 고유명사 후보 목록 생성
Pass 2 — 검색  : 신뢰도 낮은 항목·ambiguous 항목을 DuckDuckGo로 검색
Pass 3 — 검증  : 추출 결과 + 검색 스니펫을 합쳐 Claude가 공식 표기 확정

문제 유형:
  - 약어/혼용     : "TS" → "TypeScript", "넥젯" → "Next.js"
  - 오디오 오류   : "이레이저블" → "erasableSyntaxOnly", "비에스코드" → "Visual Studio Code"
  - 버전 혼용     : "타입스크립트 5점8" / "TS5.8" → "TypeScript 5.8"
  - 인물/회사명   : "일론" → "일론 머스크(Elon Musk)"
"""
import json
import re
import time
from src.pipeline import ai_client
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ── 프롬프트 ────────────────────────────────────────────────

_EXTRACT_SYSTEM = """당신은 텍스트에서 고유명사를 추출하는 전문가입니다.
응답은 반드시 유효한 JSON만 출력하세요."""

_EXTRACT_PROMPT = """아래는 YouTube 영상({source})의 원본 텍스트 일부입니다.

--- 텍스트 ---
{text}

다음 JSON 형식으로 고유명사를 추출해주세요:
{{
  "proper_nouns": [
    {{
      "raw": "텍스트 원본 표기",
      "official": "추정 공식 표기",
      "category": "tech_product | framework | library | person | company | brand | version | concept | other",
      "confidence": 0.0~1.0,
      "search_needed": true/false,
      "search_query": "검색 쿼리 (search_needed=true 일 때)"
    }}
  ],
  "ambiguous": [
    {{
      "raw": "불확실한 표기",
      "candidates": ["후보1", "후보2"],
      "reason": "불확실한 이유",
      "search_query": "이 항목을 확인하기 위한 검색 쿼리"
    }}
  ]
}}

추출 대상: 기술 스택(프레임워크·라이브러리·언어·도구·버전), 인물, 기업·서비스·제품명, 기술 개념 고유명사

규칙:
- 오탈자·약어·한국어 음차 표기는 추정 공식 표기를 함께 작성
- 확실하지 않거나 버전·인물이 포함되면 search_needed: true, search_query 작성
- confidence 0.75 미만이면 ambiguous로 분류
- 일반 명사(함수, 변수, 클래스) 제외"""


_VERIFY_SYSTEM = """당신은 기술 고유명사의 공식 표기를 웹 검색 결과를 근거로 최종 확정하는 전문가입니다.
응답은 반드시 유효한 JSON만 출력하세요."""

_VERIFY_PROMPT = """YouTube 영상 고유명사 검증 요청입니다.

제목: {title}
채널: {channel}

--- 추출된 고유명사 ---
{proper_nouns}

--- 모호한 항목 ---
{ambiguous}

--- 웹 검색 결과 ---
{search_results}

위 정보를 종합해 최종 검증 결과를 JSON으로 출력하세요.
검색 결과가 있는 항목은 검색 결과를 우선 신뢰하세요:
{{
  "verified": {{
    "원본표기": "공식표기"
  }},
  "glossary": [
    {{
      "term": "공식 표기",
      "description": "독자를 위한 한 줄 설명",
      "category": "카테고리",
      "source": "검색확인 | 모델지식"
    }}
  ],
  "warnings": [
    "주의사항"
  ],
  "search_corrections": [
    {{
      "raw": "원본 표기",
      "corrected": "검색으로 확정된 공식 표기",
      "evidence": "근거가 된 검색 스니펫 요약"
    }}
  ]
}}

- verified: raw→official 전체 매핑
- glossary: 독자에게 생소할 것만, 최대 8개
- search_corrections: 검색 결과로 수정된 항목만"""


# ── 검색 ────────────────────────────────────────────────────

def _ddg_search(query: str, max_results: int = 4) -> list[dict]:
    """DuckDuckGo 텍스트 검색. 실패 시 빈 리스트 반환."""
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return [{"title": r.get("title", ""), "body": r.get("body", ""), "href": r.get("href", "")}
                for r in results]
    except Exception as e:
        logger.warning("DDG 검색 실패 (query=%r): %s", query, e)
        return []


def _build_search_targets(proper_nouns: list[dict], ambiguous: list[dict]) -> list[dict]:
    """검색이 필요한 항목만 추려서 반환 (중복 쿼리 제거)."""
    seen_queries: set[str] = set()
    targets = []

    for noun in proper_nouns:
        if noun.get("search_needed") and noun.get("search_query"):
            q = noun["search_query"].strip()
            if q and q not in seen_queries:
                seen_queries.add(q)
                targets.append({"type": "noun", "raw": noun["raw"], "query": q})

    for item in ambiguous:
        if item.get("search_query"):
            q = item["search_query"].strip()
            if q and q not in seen_queries:
                seen_queries.add(q)
                targets.append({"type": "ambiguous", "raw": item["raw"], "query": q})

    return targets


def _run_searches(targets: list[dict]) -> dict[str, list[dict]]:
    """
    targets 리스트를 순회하며 검색 실행.
    반환: {raw_표기: [검색결과, ...]}
    """
    results: dict[str, list[dict]] = {}
    for t in targets:
        logger.info("검색: %r → %r", t["raw"], t["query"])
        hits = _ddg_search(t["query"])
        results[t["raw"]] = hits
        if hits:
            logger.debug("검색 결과 %d건 (raw=%r)", len(hits), t["raw"])
        time.sleep(0.4)  # rate limit 방지
    return results


def _format_search_results(search_map: dict[str, list[dict]]) -> str:
    """검색 결과를 Claude 프롬프트에 삽입할 텍스트로 변환."""
    if not search_map:
        return "(검색 결과 없음)"

    lines = []
    for raw, hits in search_map.items():
        lines.append(f"[{raw}]")
        if not hits:
            lines.append("  검색 결과 없음")
        for i, h in enumerate(hits[:3], 1):
            snippet = h["body"][:200].replace("\n", " ")
            lines.append(f"  {i}. {h['title']}")
            lines.append(f"     {snippet}")
            if h["href"]:
                lines.append(f"     출처: {h['href']}")
        lines.append("")
    return "\n".join(lines)


# ── 메인 API ────────────────────────────────────────────────

def extract_and_verify(text: str, title: str = "", channel: str = "",
                       source: str = "자막") -> dict:
    """
    텍스트에서 고유명사를 추출 → 웹 검색 → 검증.

    반환:
      {
        "verified":          {raw: official, ...},
        "glossary":          [{term, description, category, source}, ...],
        "warnings":          [...],
        "search_corrections":[{raw, corrected, evidence}, ...],
        "raw_proper_nouns":  [...],
        "search_count":      int,
      }
    """
    if not text or not text.strip():
        return _empty()

    sample = _sample_text(text, max_chars=12000)
    logger.info("고유명사 추출 시작 (source=%s, chars=%d)", source, len(sample))

    # ── Pass 1: 추출 ────────────────────────────────────────
    try:
        raw1 = ai_client.chat(
            _EXTRACT_SYSTEM,
            _EXTRACT_PROMPT.format(source=source, text=sample),
            max_tokens=2000,
        )
        extracted = _parse_json(raw1)
    except Exception as e:
        logger.warning("고유명사 추출 실패: %s", e)
        return _empty()

    proper_nouns = extracted.get("proper_nouns", [])
    ambiguous    = extracted.get("ambiguous", [])
    logger.info("추출 완료: 확정 %d개, 모호 %d개", len(proper_nouns), len(ambiguous))

    if not proper_nouns and not ambiguous:
        return _empty()

    # ── Pass 2: 검색 ────────────────────────────────────────
    targets = _build_search_targets(proper_nouns, ambiguous)
    logger.info("검색 대상 %d개", len(targets))

    search_map: dict[str, list[dict]] = {}
    if targets:
        search_map = _run_searches(targets)
        logger.info("검색 완료: %d개 항목", len(search_map))

    search_text = _format_search_results(search_map)

    # ── Pass 3: 검증 ────────────────────────────────────────
    try:
        raw2 = ai_client.chat(
            _VERIFY_SYSTEM,
            _VERIFY_PROMPT.format(
                title=title,
                channel=channel,
                proper_nouns=json.dumps(proper_nouns, ensure_ascii=False, indent=2),
                ambiguous=json.dumps(ambiguous, ensure_ascii=False, indent=2),
                search_results=search_text,
            ),
            max_tokens=2500,
        )
        verified = _parse_json(raw2)
    except Exception as e:
        logger.warning("고유명사 검증 실패: %s", e)
        fallback = {n["raw"]: n["official"] for n in proper_nouns if n.get("confidence", 1) >= 0.75}
        return {"verified": fallback, "glossary": [], "warnings": [],
                "search_corrections": [], "raw_proper_nouns": proper_nouns, "search_count": len(search_map)}

    result = {
        "verified":           verified.get("verified", {}),
        "glossary":           verified.get("glossary", [])[:8],
        "warnings":           verified.get("warnings", []),
        "search_corrections": verified.get("search_corrections", []),
        "raw_proper_nouns":   proper_nouns,
        "search_count":       len(search_map),
    }
    logger.info(
        "검증 완료: 확정 %d개 (검색보정 %d개), 용어집 %d개, 경고 %d개",
        len(result["verified"]), len(result["search_corrections"]),
        len(result["glossary"]), len(result["warnings"]),
    )
    return result


def apply_verified_nouns(text: str, verified: dict[str, str]) -> str:
    """검증된 고유명사 사전으로 텍스트 내 표기를 치환한다."""
    if not verified or not text:
        return text
    for raw, official in sorted(verified.items(), key=lambda x: -len(x[0])):
        if raw and official and raw != official:
            text = re.sub(re.escape(raw), official, text, flags=re.IGNORECASE)
    return text


# ── 내부 유틸 ────────────────────────────────────────────────

def _empty() -> dict:
    return {"verified": {}, "glossary": [], "warnings": [],
            "search_corrections": [], "raw_proper_nouns": [], "search_count": 0}


def _sample_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    third = max_chars // 3
    mid = len(text) // 2
    return (text[:third]
            + "\n\n[...중략...]\n\n"
            + text[mid - third // 2: mid + third // 2]
            + "\n\n[...중략...]\n\n"
            + text[-third:])


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())
