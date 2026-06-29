# YouTube Live Summary Agent

YouTube 채널의 **라이브 방송 시작/종료**와 **신규 영상 업로드**를 자동 감지해 AI로 요약하는 에이전트입니다.

- 채널을 등록하면 폴링 루프가 상태를 주기적으로 확인하고, 이벤트 발생 시 실시간 채팅형 UI에 결과를 올립니다.
- Claude · OpenAI · Gemini · Grok · 로컬 LLM(Ollama 등) 모두 지원하며, YouTube API 키와 AI 키를 UI에서 바로 변경할 수 있습니다.

---

## 주요 기능

| 기능 | 설명 |
|---|---|
| 라이브 감지 | 채널 라이브 시작/종료 자동 감지 |
| 신규 영상 감지 | 업로드 즉시 감지 (uploads 플레이리스트, 2유닛) |
| AI 요약 | 자막·채팅 기반 map-reduce 요약 |
| 고유명사 검증 | 추출 → DuckDuckGo 검색 → AI 검증 3-pass |
| 다중 AI 지원 | Claude / OpenAI / Gemini / Grok / Custom |
| UI 키 관리 | YouTube·AI API 키를 재시작 없이 UI에서 변경 |
| 채널 관리 | URL · @핸들 · 채널ID 형식 모두 지원 |
| 직접 요약 | 채팅창에 YouTube URL/ID 입력 시 즉시 요약 |
| 채널별 알림 | 브라우저 푸시 알림 (채널별 on/off, 10초 자동 소멸) |
| 이중 스토리지 | DB 있으면 DB 사용, 없으면 파일 자동 전환 |
| 알림 | Slack · Notion 연동 (선택) |

---

## 빠른 시작

### 1. 클론

```bash
git clone https://github.com/goblin8621/youtube-live-summary-agent.git
cd youtube-live-summary-agent
```

### 2. 가상환경 & 패키지 설치

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 환경변수 설정

```bash
cp .env.example .env
```

`.env` 파일을 열어 최소한 아래 두 항목을 입력합니다.

```env
YOUTUBE_API_KEY=AIza...          # YouTube Data API v3 키
ANTHROPIC_API_KEY=sk-ant-...     # Claude 사용 시 필수 (다른 AI는 UI에서 설정 가능)
```

> **API 키 없이 시작하는 경우:** 키를 비워두고 실행한 뒤 UI의 `⚙ AI 모델 설정` 패널에서 입력할 수 있습니다.

### 4. 실행

```bash
python3 main.py
```

브라우저에서 `http://localhost:8000` 을 열면 UI가 표시됩니다.

---

## Docker로 실행

```bash
# .env 파일 준비 후
docker compose up -d
```

`docker-compose.yml` 기본 설정으로 `8000` 포트가 노출됩니다.

---

## UI 사용법

### 채널 추가

사이드바 상단 입력창에 아래 형식 중 하나를 입력하고 `+` 버튼을 누르거나 Enter를 칩니다.

```
https://www.youtube.com/@channelhandle
@channelhandle
UCxxxxxxxxxxxxxxxxxxxxxxxx          ← 채널 ID 직접 입력
https://www.youtube.com/channel/UC...
```

### 영상 직접 요약

채팅 입력창에 YouTube URL 또는 영상 ID를 입력하고 Enter를 누릅니다.

```
https://www.youtube.com/watch?v=dQw4w9WgXcQ
https://youtu.be/dQw4w9WgXcQ
dQw4w9WgXcQ                         ← 11자리 ID 직접 입력
```

> 다른 텍스트를 입력하면 아무 반응이 없습니다 (URL/ID에만 반응).

### AI 모델 변경

사이드바 하단 `⚙ YouTube · AI 설정` 버튼을 클릭합니다.

```
YouTube 인증
  API Key  [••••••••]

AI 모델
  Provider  [Claude (Anthropic) ▼]
  모델      [claude-sonnet-4-6   ]
  API Key   [••••••••]

  [저장]
```

지원 Provider:

| Provider | 기본 모델 | 비고 |
|---|---|---|
| Claude (Anthropic) | claude-sonnet-4-6 | `.env`의 `ANTHROPIC_API_KEY` 사용 |
| OpenAI | gpt-4o | |
| Grok (xAI) | grok-3 | |
| Gemini (Google) | gemini-2.0-flash | OpenAI 호환 엔드포인트 사용 |
| Custom | (직접 입력) | Base URL 입력 → Ollama, LM Studio, vLLM 등 |

### 피드 필터

하단 버튼으로 표시 항목을 필터링합니다.

| 버튼 | 표시 내용 |
|---|---|
| 전체 | 모든 이벤트 |
| 요약만 | 라이브 요약 + 영상 요약 |
| 라이브 이벤트 | 시작 · 채팅 수집 · 종료 |
| 피드 초기화 | 화면 비우기 (DB 삭제 아님) |

---

## 스토리지 모드

앱 시작 시 `data/agent.db` 파일 존재 여부로 자동 결정됩니다.

| 모드 | 조건 | 설정 저장 위치 | 요약 저장 위치 |
|---|---|---|---|
| **DB 모드** | `agent.db` 존재 | SQLite `app_settings` 테이블 | `summaries` / `video_summaries` 테이블 |
| **파일 모드** | `agent.db` 없음 | `data/config.json` | `data/summaries/{채널ID}/{날짜}/` |

파일 모드에서 요약 데이터는 **10일 후 자동 삭제**됩니다.

---

## 환경변수 전체 목록

| 변수 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `YOUTUBE_API_KEY` | 권장 | `""` | YouTube Data API v3 키 (UI에서도 설정 가능) |
| `ANTHROPIC_API_KEY` | Claude 사용 시 | `""` | Anthropic API 키 |
| `POLL_INTERVAL_SECONDS` | 아니요 | `300` | 채널 폴링 간격 (초) |
| `SLACK_BOT_TOKEN` | 아니요 | `""` | Slack 알림용 봇 토큰 |
| `SLACK_CHANNEL_ID` | 아니요 | `#youtube-summaries` | Slack 채널 |
| `NOTION_TOKEN` | 아니요 | `""` | Notion 연동 토큰 |
| `NOTION_DATABASE_ID` | 아니요 | `""` | Notion 데이터베이스 ID |
| `DB_PATH` | 아니요 | `./data/agent.db` | SQLite 저장 경로 |
| `LOG_LEVEL` | 아니요 | `INFO` | 로그 레벨 |

---

## YouTube API 키 발급

1. [Google Cloud Console](https://console.cloud.google.com/) → 프로젝트 생성
2. **API 및 서비스** → **라이브러리** → `YouTube Data API v3` 활성화
3. **사용자 인증 정보** → **API 키** 생성
4. (권장) API 키 제한 → YouTube Data API v3만 허용

> **무료 할당량:** 하루 10,000유닛. 채널 1개 폴링(5분 간격) 시 약 576유닛/일 소비.

---

## 로컬 LLM 연결 (Custom Provider)

[Ollama](https://ollama.com/)를 예시로 설명합니다.

```bash
# Ollama 설치 후 모델 실행
ollama run llama3.1
```

UI 설정 패널에서:
- Provider: **Custom (OpenAI 호환)**
- Base URL: `http://localhost:11434/v1`
- 모델: `llama3.1`
- API Key: (비워도 됨)

LM Studio, vLLM, text-generation-webui 등 OpenAI 호환 서버라면 동일하게 연결됩니다.

---

## 프로젝트 구조

```
.
├── main.py                        # 진입점: FastAPI 서버 + 폴링 루프 병렬 실행
├── requirements.txt
├── .env.example
├── docker-compose.yml
├── Dockerfile
├── static/
│   └── index.html                 # 채팅형 실시간 UI (WebSocket)
└── src/
    ├── config.py                  # 환경변수 (pydantic-settings)
    ├── watcher/
    │   ├── youtube_client.py      # 런타임 키 교체 가능한 YouTube 클라이언트
    │   ├── live_detector.py       # 라이브 감지
    │   ├── video_detector.py      # 신규 영상 감지 (uploads 플레이리스트)
    │   ├── chat_collector.py      # 라이브 채팅 수집
    │   └── caption_watcher.py     # 자막 수집
    ├── pipeline/
    │   ├── ai_client.py           # 통합 AI 클라이언트 (Claude/OpenAI/Gemini/Grok/Custom)
    │   ├── noun_verifier.py       # 고유명사 3-pass 검증 + DuckDuckGo 검색
    │   ├── preprocessor.py        # 텍스트 전처리 & 청킹
    │   ├── summarizer.py          # 라이브 요약 (map-reduce)
    │   ├── video_summarizer.py    # 영상 요약
    │   └── reporter.py            # 마크다운 리포트 생성
    ├── scheduler/
    │   └── poller.py              # 폴링 루프 & 이벤트 처리
    ├── server/
    │   └── app.py                 # FastAPI 앱 & REST API & WebSocket
    ├── storage/
    │   └── database.py            # SQLite 스키마 & CRUD
    └── notifiers/
        ├── slack_notifier.py
        └── notion_notifier.py
```

---

## REST API

| Method | Path | 설명 |
|---|---|---|
| `WS` | `/ws` | 실시간 이벤트 스트림 |
| `GET` | `/api/channels` | 모니터링 채널 목록 |
| `POST` | `/api/channels` | 채널 추가 |
| `DELETE` | `/api/channels/{id}` | 채널 제거 |
| `GET` | `/api/settings` | AI + YouTube 설정 조회 |
| `PUT` | `/api/settings` | 설정 변경 (재시작 불필요) |
| `POST` | `/api/summarize` | 영상 URL/ID 즉시 요약 |
| `GET` | `/api/history` | 과거 요약 히스토리 |
| `GET` | `/api/live` | 현재 라이브 세션 목록 |

---

## 개발 히스토리

이 프로젝트의 전체 설계 결정과 구현 흐름은 [`DEVELOPMENT_HISTORY.md`](./DEVELOPMENT_HISTORY.md)에 정리되어 있습니다.

---

## 라이선스

MIT
