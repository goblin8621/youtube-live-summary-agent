"""전처리 함수 단위 테스트."""
import pytest
from src.pipeline.preprocessor import (
    build_caption_text,
    build_chat_text,
    split_into_chunks,
    MAX_CHARS_PER_CHUNK,
)


def test_build_caption_text_timestamp():
    captions = [
        {"start_sec": 0, "text": "안녕하세요"},
        {"start_sec": 65, "text": "오늘 방송 시작합니다"},
        {"start_sec": 3661, "text": "1시간 넘었네요"},
    ]
    result = build_caption_text(captions)
    assert "[00:00]" in result
    assert "[01:05]" in result
    assert "[01:01:01]" in result
    assert "안녕하세요" in result


def test_build_chat_text_filters_empty():
    messages = [
        {"author": "유저A", "message": ""},
        {"author": "유저B", "message": "반갑습니다"},
    ]
    result = build_chat_text(messages)
    assert "유저A" not in result
    assert "유저B: 반갑습니다" in result


def test_split_into_chunks_single():
    text = "짧은 텍스트"
    chunks = split_into_chunks(text, max_chars=100)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_split_into_chunks_multiple():
    lines = [f"라인 {i}: " + "a" * 100 for i in range(100)]
    text = "\n".join(lines)
    chunks = split_into_chunks(text, max_chars=500)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 600  # 마지막 줄 오버런 허용 마진


def test_build_chat_text_samples_large_input():
    messages = [{"author": f"유저{i}", "message": f"메시지{i}"} for i in range(5000)]
    result = build_chat_text(messages)
    line_count = len(result.split("\n"))
    assert line_count <= 2100  # 샘플링 적용됨
