"""
통합 AI 클라이언트.
provider: "claude" | "openai" | "grok" | "gemini" | "custom"
런타임에 /api/settings 로 변경 가능, DB에 영속.
"""
from src.utils.logger import get_logger

logger = get_logger(__name__)

_GROK_BASE_URL   = "https://api.x.ai/v1"
_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

PROVIDER_DEFAULTS: dict[str, str] = {
    "claude": "claude-sonnet-4-6",
    "openai": "gpt-4o",
    "grok":   "grok-3",
    "gemini": "gemini-2.0-flash",
    "custom": "",
}

# 런타임 설정 (main.py init 후 DB에서 갱신됨)
_config: dict = {
    "provider": "claude",
    "model":    "claude-sonnet-4-6",
    "api_key":  "",
    "base_url": "",  # custom provider 전용
}


def get_config() -> dict:
    """현재 설정 반환 (api_key는 마스킹)."""
    c = dict(_config)
    key = c.pop("api_key", "")
    c["api_key_masked"] = f"...{key[-4:]}" if len(key) > 4 else ("설정됨" if key else "")
    return c


def update_config(provider: str | None = None, model: str | None = None,
                  api_key: str | None = None, base_url: str | None = None):
    if provider and provider in PROVIDER_DEFAULTS:
        _config["provider"] = provider
        if model is None:
            _config["model"] = PROVIDER_DEFAULTS[provider]
    if model:
        _config["model"] = model
    if api_key is not None:
        _config["api_key"] = api_key
    if base_url is not None:
        _config["base_url"] = base_url
    logger.info("AI 설정: provider=%s model=%s", _config["provider"], _config["model"])


def chat(system: str, user: str, max_tokens: int = 2000) -> str:
    """현재 provider로 메시지 생성 후 텍스트 반환."""
    provider = _config["provider"]
    model    = _config["model"]
    key      = _config["api_key"]

    if provider == "claude":
        return _chat_claude(system, user, max_tokens, model, key)
    elif provider in ("openai", "grok", "gemini", "custom"):
        return _chat_openai(system, user, max_tokens, model, key, provider)
    else:
        raise ValueError(f"지원하지 않는 provider: {provider}")


def _chat_claude(system: str, user: str, max_tokens: int,
                 model: str, key: str) -> str:
    import anthropic
    from src.config import settings
    client = anthropic.Anthropic(api_key=key or settings.anthropic_api_key)
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return msg.content[0].text


def _chat_openai(system: str, user: str, max_tokens: int,
                 model: str, key: str, provider: str) -> str:
    import openai
    _base_urls = {
        "grok":   _GROK_BASE_URL,
        "gemini": _GEMINI_BASE_URL,
        "custom": _config.get("base_url", ""),
    }
    kwargs: dict = {"api_key": key or "none"}  # Ollama 등 key 불필요 시 dummy
    base = _base_urls.get(provider, "")
    if base:
        kwargs["base_url"] = base
    client = openai.OpenAI(**kwargs)
    resp = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
    )
    return resp.choices[0].message.content
