# YouTube Live Summary Agent — 개발 히스토리

다른 환경에서도 개발 맥락을 이어갈 수 있도록 이 세션의 설계 결정과 구현 내역을 시간 순으로 정리합니다.

---

## Phase 1 · 설계

**요청:** YouTube 채널 라이브 방송 시작을 감지하고, 종료 시 AI로 요약하는 에이전트 설계

**설계 결정사항:**
- YouTube Data API v3 — `search.list(eventType=live)` + `channels.list` 조합
- API 유닛 절약: `search.list` = 100유닛, `channels.list` = 1유닛 → 폴링은 최소 유닛 경로 우선
- Claude API (`claude-sonnet-4-6`) 로 요약
- FastAPI + uvicorn 웹서버 + asyncio 폴링 루프를 `asyncio.gather()`로 병렬 실행
- SQLite (`aiosqlite`) 로 세션/채팅/자막/요약 영속화
- WebSocket으로 UI 실시간 브로드캐스트

---

## Phase 2 · 초기 구현

**생성된 파일 목록:**

```
requirements.txt
main.py
src/
  config.py              ← pydantic-settings BaseSettings
  utils/logger.py
  storage/database.py    ← 5개 테이블 (live_sessions, chat_messages, captions, summaries, monitored_channels)
  watcher/
    live_detector.py     ← check_channel_live()
    chat_collector.py    ← ChatCollector 클래스
    caption_watcher.py   ← fetch_captions() youtube-transcript-api 사용
  pipeline/
    preprocessor.py      ← build_caption_text(), build_chat_text(), split_into_chunks()
    summarizer.py        ← map-reduce 청킹 (80,000자/청크)
    reporter.py          ← 마크다운 리포트 생성
  scheduler/poller.py    ← poll_once(), run_polling_loop()
  server/app.py          ← FastAPI + WebSocket /ws
  notifiers/
    slack_notifier.py
    notion_notifier.py
static/index.html        ← 첫 번째 UI
```

**핵심 구조:**
```python
# main.py
await asyncio.gather(
    uvicorn.Server(config).serve(),
    run_polling_loop(),
)
```

---

## Phase 3 · 채팅형 UI

**요청:** 결과를 채팅창처럼 위로 올라가는 형태로

**변경사항 (`static/index.html`):**
- 다크 테마 (`#0f0f10`)
- 메시지 버블 슬라이드업 애니메이션 (`slideUp 0.35s`)
- 이벤트 타입별 색상 코딩:
  - 🔴 `live_start` — red
  - 🔵 `chat_collected` — blue
  - 🟡 `live_end` — amber
  - 🟣 `summary_ready` — purple
- 필터 버튼 (전체 / 요약만 / 라이브 이벤트)
- 자동 스크롤 + 맨 아래 버튼
- WebSocket 자동 재연결 (3초)
- 서버 없을 때 데모 모드 자동 실행

---

## Phase 4 · 다중 채널 관리

**요청:** 채널 여러 개 추가 기능

**변경사항:**

`database.py`
- `monitored_channels` 테이블 추가 (`channel_id`, `title`, `thumbnail_url`, `subscriber_count`, `added_at`, `last_video_id`)

`server/app.py`
- `GET /api/channels` — 채널 목록
- `POST /api/channels` — 채널 추가 (`_resolve_channel_id()`: URL / @핸들 / 채널ID 모두 수용)
- `DELETE /api/channels/{channel_id}` — 채널 제거
- `_runtime_channels: set[str]` — 재시작 없이 즉시 폴링에 반영

`static/index.html`
- 왼쪽 사이드바에 채널 목록 표시
- 채널 추가 패널 (URL / @핸들 / 채널ID 입력)
- 라이브 중인 채널에 빨간 점 배지

---

## Phase 5 · 신규 영상 감지

**요청:** 라이브 외에 신규 영상 업로드도 감지해서 요약

**API 유닛 절약 결정:**
- `search.list` = 100유닛 → 사용 안 함
- `channels.list(1유닛)` + `playlistItems.list(1유닛)` = 2유닛으로 동일 결과

**새 파일:**

`src/watcher/video_detector.py`
```python
get_new_videos(channel_id, since_video_id)   # since_video_id 이후 신규만 반환
get_latest_video_id(channel_id)              # 초기 기준점 설정 (과거 영상 요약 방지)
_uploads_playlist_cache: dict                # 플레이리스트 ID 세션 캐싱
```

`src/pipeline/video_summarizer.py`
```python
summarize_video(video, captions)
_parse_iso_duration("PT1H30M45S") → "1시간 30분 45초"
```

`database.py`
- `video_summaries` 테이블 추가
- `get_last_video_id()`, `set_last_video_id()`, `save_video_summary()` 추가

`poller.py`
- `_handle_new_video()`, `_run_video_summary_pipeline()` 추가
- `poll_once()` 에서 라이브 감지 + 신규 영상 감지 병렬 처리

**첫 실행 시 스팸 방지:**
- `last_video_id is None` → 기준점만 저장, 요약하지 않음
- `last_video_id` 있을 때만 이후 영상 요약

---

## Phase 6 · 채팅창 직접 요약 입력

**요청:** 채팅 입력창에서 YouTube URL/ID 입력 시 이전 영상도 요약. URL/ID 외 텍스트는 무반응.

`server/app.py`
```python
def _extract_video_id(raw: str) -> str | None:
    # youtu.be/ID
    # watch?v=ID
    # /shorts/ID
    # 11자리 직접 입력
    # /embed/ID

POST /api/summarize  # 영상 정보 조회 → broadcast(video_detected) → 백그라운드 요약
```

**`static/index.html` — 채팅 입력창 동작:**
- 실시간 유효성 검사 (정규식)
  - 유효: teal 테두리, 전송 버튼 활성화
  - 무효: 시각 반응 없음, Enter 시 흔들림 애니메이션만
- 내가 보낸 메시지: 우측 정렬 teal 버블로 URL 표시
- 이벤트 색상 추가:
  - 🟠 `video_detected` — orange
  - 🩵 `video_summary_ready` — teal

---

## Phase 7 · 고유명사 검증 파이프라인

**요청:** 요약 시 고유명사 검증 과정 필요 (오디오 오류, 약어, 음차 등)
**추가 요청:** 검증 시 웹 검색도 수행

**새 파일: `src/pipeline/noun_verifier.py`**

3-Pass 파이프라인:
```
Pass 1 (추출) → Pass 2 (DDG 검색) → Pass 3 (검증)
```

**Pass 1 — Claude로 추출:**
```json
{
  "proper_nouns": [
    {"raw": "넥젯", "official": "Next.js", "confidence": 0.6,
     "search_needed": true, "search_query": "Next.js framework"}
  ],
  "ambiguous": [
    {"raw": "리액트쿼리", "candidates": ["React Query", "TanStack Query"],
     "search_query": "React Query TanStack"}
  ]
}
```

**Pass 2 — DuckDuckGo 검색:**
- `duckduckgo-search==6.3.7` 패키지 사용 (API 키 불필요)
- `search_needed: true` 항목 + ambiguous 항목만 검색
- 중복 쿼리 제거, 0.4초 rate limit
- 검색 실패 시 빈 리스트 반환 (파이프라인 중단 없음)

**Pass 3 — 검증:**
- 검색 스니펫 + 추출 결과 합쳐서 Claude가 공식 표기 최종 확정
- `search_corrections` 필드로 검색 근거 포함

```python
extract_and_verify(text, title, channel, source)
→ {verified, glossary, warnings, search_corrections, search_count}

apply_verified_nouns(text, verified)  # 정규식으로 본문 치환
```

`summarizer.py`, `video_summarizer.py` 모두 동일 패턴 적용:
1. `extract_and_verify()` 실행
2. `apply_verified_nouns()` 로 본문 치환 후 요약
3. 결과에 `glossary`, `noun_verification` 포함

---

## Phase 8 · AI 다중 공급자 지원

**요청:** UI에서 모델 정보 입력 (Claude / OpenAI / Grok 선택)

**새 파일: `src/pipeline/ai_client.py`**
```python
PROVIDER_DEFAULTS = {
    "claude": "claude-sonnet-4-6",
    "openai": "gpt-4o",
    "grok":   "grok-3",
}
_config = {"provider", "model", "api_key"}

chat(system, user, max_tokens) → str   # 현재 설정으로 호출
update_config(provider, model, api_key)
get_config()                            # api_key 마스킹 후 반환
```

기존 파이프라인 파일 변경:
- `summarizer.py`, `video_summarizer.py`, `noun_verifier.py`
  - `anthropic.Anthropic(...)` 직접 생성 제거
  - `ai_client.chat(system, user, max_tokens)` 로 통일

`database.py`
- `app_settings` 테이블 추가 (`key TEXT PRIMARY KEY`, `value TEXT`)
- `get_setting(key)`, `set_setting(key, value)` 추가

`server/app.py`
- `GET /api/settings` — 현재 설정 반환 (api_key 마스킹)
- `PUT /api/settings` — 설정 변경 + DB 저장

`main.py`
- 시작 시 DB에서 `ai.provider`, `ai.model`, `ai.api_key` 복원

**UI 설정 패널 (사이드바 하단):**
- `⚙ AI 모델 설정` 토글 버튼
- provider 탭 3개 (Claude / OpenAI / Grok)
- 모델 입력 (datalist 자동완성)
- API Key 입력 (마스킹 표시)

---

## Phase 9 · Gemini + Custom LLM 추가

**요청:** 제미나이나 커스텀 LLM도 지원

**`ai_client.py` 변경:**
```python
PROVIDER_DEFAULTS = {
    ...
    "gemini": "gemini-2.0-flash",
    "custom": "",
}
_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
_config["base_url"] = ""   # custom provider 전용
```

- **Gemini:** Google 공식 OpenAI 호환 엔드포인트 사용 → openai SDK 그대로 재활용
- **Custom:** `base_url` 직접 입력 → Ollama, LM Studio, vLLM 등 OpenAI 호환 서버 모두 지원
- `api_key or "none"` — API 키 없는 로컬 서버도 SDK 에러 없이 처리

**모델 자동완성 목록:**
| Provider | 기본값 | 선택지 |
|---|---|---|
| Claude | claude-sonnet-4-6 | opus-4-8, haiku-4-5-20251001 |
| OpenAI | gpt-4o | gpt-4o-mini, gpt-4.1, gpt-4.1-mini, o3 |
| Grok | grok-3 | grok-3-mini, grok-2 |
| Gemini | gemini-2.0-flash | 2.0-flash-lite, 1.5-pro, 1.5-flash |
| Custom | (없음) | 자유 입력 |

**UI:** provider 탭 5개 → 드롭다운으로 교체, Custom 선택 시 Base URL 입력창 노출

---

## Phase 10 · YouTube API 키도 UI 관리

**요청:** YouTube 인증도 UI로 설정

**새 파일: `src/watcher/youtube_client.py`**
```python
_runtime_key: str = ""
_cached_client = None
_cached_key: str = ""

set_key(key)      # 키 변경 + 캐시 무효화
get_key()         # runtime_key or settings.youtube_api_key (.env 폴백)
get_client()      # 키 변경 시에만 재생성 (캐싱)
```

**영향받은 파일 전체 교체:**
- `live_detector.py` — `_youtube = build(...)` 제거 → `youtube_client.get_client().xxx()`
- `video_detector.py` — 동일
- `chat_collector.py` — 동일
- `server/app.py` — 동일

`config.py`
- `youtube_api_key: str = ""` (optional) → .env 없이도 기동, UI에서만 설정 가능

`settings` API 확장:
- `PUT /api/settings` 에 `youtube_api_key` 필드 추가
- DB에 `yt.api_key` 저장, 재시작 시 자동 복원

**최종 UI 설정 패널 구조:**
```
⚙ AI 모델 설정
├── YouTube ──────────────────
│   └── API Key [마스킹 표시]
├── ──────────────────────────
├── AI 모델 ──────────────────
│   ├── Provider [드롭다운 5개]
│   ├── 모델 [자동완성]
│   ├── Base URL [Custom 시만 표시]
│   └── AI API Key [마스킹 표시]
└── [저장]
```

---

## Phase 11 · GitHub 퍼블릭 레포 배포

`.gitignore` 설정:
- 제외: `.env`, `data/`, `reports/`, `__pycache__/`, `.claude/`

`.env.example` 생성:
```
YOUTUBE_API_KEY=        # UI에서도 설정 가능
ANTHROPIC_API_KEY=      # Claude 사용 시, 다른 provider는 UI에서
SLACK_BOT_TOKEN=        # 선택
NOTION_TOKEN=           # 선택
POLL_INTERVAL_SECONDS=300
```

**레포:** https://github.com/goblin8621/youtube-live-summary-agent
- 36개 파일, 3,582줄, 브랜치: `main`

---

## 최종 아키텍처 요약

```
main.py
  └─ asyncio.gather(FastAPI 서버, 폴링 루프)

폴링 루프 (기본 5분마다, .env POLL_INTERVAL_SECONDS 조정)
  ├─ 라이브 감지 → 채팅 수집 → 종료 시 요약 파이프라인
  └─ 신규 영상 감지 → 영상 요약 파이프라인

요약 파이프라인 (라이브 / 영상 공통)
  1. 자막 / 채팅 수집
  2. 고유명사 3-pass 검증
     └─ Pass1 추출 → Pass2 DDG 검색 → Pass3 검증 + glossary
  3. 치환 후 map-reduce 요약 (80,000자/청크)
  4. DB 저장 + WebSocket 브로드캐스트

설정 관리 (모두 런타임 교체 가능, 재시작 불필요)
  ├─ YouTube API Key     → youtube_client._runtime_key
  ├─ AI Provider + Model → ai_client._config
  ├─ AI API Key          → ai_client._config
  └─ Custom Base URL     → ai_client._config["base_url"]
  모두 SQLite app_settings 테이블에 영속화

WebSocket 이벤트 타입
  live_start / chat_collected / live_end / summary_ready
  video_detected / video_summary_ready
  channel_added / channel_removed
```

## REST API 목록

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/channels` | 모니터링 채널 목록 |
| POST | `/api/channels` | 채널 추가 (URL/@핸들/ID) |
| DELETE | `/api/channels/{id}` | 채널 제거 |
| GET | `/api/settings` | AI + YouTube 설정 조회 |
| PUT | `/api/settings` | 설정 변경 + DB 저장 |
| POST | `/api/summarize` | 영상 URL/ID 직접 요약 |
| GET | `/api/history` | 과거 요약 히스토리 |
| GET | `/api/live` | 현재 진행 중인 라이브 세션 |
| WS | `/ws` | 실시간 이벤트 스트림 |

## 의존성 (requirements.txt)

| 패키지 | 용도 |
|---|---|
| google-api-python-client | YouTube Data API v3 |
| anthropic | Claude API |
| openai | OpenAI / Grok / Gemini / Custom |
| fastapi + uvicorn | 웹서버 |
| aiosqlite | 비동기 SQLite |
| youtube-transcript-api | 자막 수집 |
| duckduckgo-search | 고유명사 웹 검색 |
| pydantic-settings | 환경변수 관리 |
| tenacity | API 호출 재시도 |
| slack-sdk / notion-client | 알림 (선택) |
| rich | 터미널 로그 |
