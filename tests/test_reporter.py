"""리포트 생성 테스트."""
from src.pipeline.reporter import build_report, _ts_to_seconds


def test_ts_to_seconds():
    assert _ts_to_seconds("01:30:00") == 5400
    assert _ts_to_seconds("05:30") == 330
    assert _ts_to_seconds("invalid") == 0


def test_build_report_contains_key_fields():
    session = {
        "id": "sess1",
        "title": "테스트 방송",
        "channel_title": "테스트 채널",
        "video_id": "abc123",
        "started_at": "2025-01-01T10:00:00Z",
        "ended_at": "2025-01-01T12:00:00Z",
        "peak_viewers": 1234,
        "duration_secs": 7200,
    }
    summary = {
        "summary_text": "방송 전체 요약입니다.",
        "key_topics": ["주제1", "주제2"],
        "highlights": [{"timestamp": "01:00:00", "description": "중요 발표"}],
        "one_liner": "한줄 요약",
    }
    report = build_report(session, summary)
    assert "테스트 방송" in report
    assert "1,234명" in report
    assert "주제1" in report
    assert "중요 발표" in report
    assert "한줄 요약" in report
