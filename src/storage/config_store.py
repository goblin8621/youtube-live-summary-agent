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
