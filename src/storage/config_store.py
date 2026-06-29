"""JSON 파일 기반 설정 저장소 (data/config.json). DB 없을 때 사용."""
import json
import threading
from pathlib import Path
from src.utils.logger import get_logger

logger = get_logger(__name__)

_CONFIG_PATH = Path("./data/config.json")
_lock = threading.Lock()


def _read() -> dict:
    if not _CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("config.json 읽기 실패: %s", e)
        return {}


def _write(data: dict):
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def get(section: str, key: str) -> str:
    return _read().get(section, {}).get(key, "")


def save(section: str, key: str, value: str):
    with _lock:
        data = _read()
        data.setdefault(section, {})[key] = value
        _write(data)


def save_many(updates: dict[str, dict[str, str]]):
    with _lock:
        data = _read()
        for section, kv in updates.items():
            data.setdefault(section, {}).update(kv)
        _write(data)
        logger.info("config.json 저장: %s", list(updates.keys()))


# ── 채널 목록 ─────────────────────────────────────────────────

def get_channels() -> list[dict]:
    return _read().get("channels", [])


def add_channel(channel: dict) -> bool:
    """채널 추가. 이미 존재하면 False 반환."""
    with _lock:
        data = _read()
        channels = data.setdefault("channels", [])
        if any(c["channel_id"] == channel["channel_id"] for c in channels):
            return False
        channels.append(channel)
        _write(data)
    return True


def remove_channel(channel_id: str) -> str | None:
    """채널 제거. 제거된 채널 title 반환, 없으면 None."""
    with _lock:
        data = _read()
        channels = data.get("channels", [])
        target = next((c for c in channels if c["channel_id"] == channel_id), None)
        if not target:
            return None
        data["channels"] = [c for c in channels if c["channel_id"] != channel_id]
        _write(data)
    return target.get("title", "")
