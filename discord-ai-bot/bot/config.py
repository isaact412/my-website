"""Loads settings from the .env file and checks they look sane."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


class ConfigError(Exception):
    """Raised when .env is missing something important."""


@dataclass(frozen=True)
class ProviderConfig:
    name: str          # "groq" | "openrouter" | "ollama"
    base_url: str
    api_key: str
    model: str         # may be "auto"


@dataclass(frozen=True)
class Settings:
    discord_token: str
    owner_user_id: int
    dev_guild_id: int | None
    log_level: str
    database_path: Path
    allow_paid_models: bool
    providers: list[ProviderConfig]
    ai_max_calls_per_minute: int
    ai_daily_call_limit: int
    ai_user_cooldown_seconds: int
    background_daily_call_limit: int
    history_daily_call_limit: int


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _int_or_none(name: str) -> int | None:
    raw = _get(name)
    if not raw:
        return None
    if not raw.isdigit():
        raise ConfigError(f"{name} must be a number (a Discord ID), got: {raw!r}")
    return int(raw)


def _int(name: str, default: int) -> int:
    raw = _get(name)
    if not raw:
        return default
    if not raw.isdigit():
        raise ConfigError(f"{name} must be a whole number, got: {raw!r}")
    return int(raw)


def _bool(name: str, default: bool) -> bool:
    raw = _get(name).lower()
    if not raw:
        return default
    if raw in ("true", "1", "yes"):
        return True
    if raw in ("false", "0", "no"):
        return False
    raise ConfigError(f"{name} must be true or false, got: {raw!r}")


# Every provider here speaks the same "OpenAI-compatible" API.
_PROVIDER_DEFAULTS = {
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "GROQ_MODEL", "auto"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "OPENROUTER_MODEL", "openrouter/free"),
    "ollama": (None, None, "OLLAMA_MODEL", ""),
}


def _load_providers() -> list[ProviderConfig]:
    chain = [p.strip().lower() for p in _get("AI_PROVIDER_CHAIN", "groq").split(",") if p.strip()]
    providers = []
    for name in chain:
        if name not in _PROVIDER_DEFAULTS:
            raise ConfigError(
                f"Unknown provider {name!r} in AI_PROVIDER_CHAIN. Free options: groq, openrouter, ollama. "
                "(Paid providers aren't built in yet, on purpose.)"
            )
        base_url, key_var, model_var, default_model = _PROVIDER_DEFAULTS[name]
        if name == "ollama":
            base_url = _get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/") + "/v1"
            api_key = "ollama"  # Ollama ignores it, but the request format needs one
        else:
            api_key = _get(key_var)
            if not api_key:
                raise ConfigError(f"{name} is in AI_PROVIDER_CHAIN but {key_var} is empty in .env.")
        model = _get(model_var, default_model) or default_model
        if not model:
            raise ConfigError(f"{name} is in AI_PROVIDER_CHAIN but {model_var} is empty in .env.")
        providers.append(ProviderConfig(name=name, base_url=base_url, api_key=api_key, model=model))
    return providers


def load_settings() -> Settings:
    load_dotenv()  # reads .env from the folder you run the bot in

    token = _get("DISCORD_TOKEN")
    if not token:
        raise ConfigError("DISCORD_TOKEN is empty. Paste your bot token into .env.")

    owner = _int_or_none("OWNER_USER_ID")
    if owner is None:
        raise ConfigError("OWNER_USER_ID is empty. Put your Discord user ID in .env.")

    return Settings(
        discord_token=token,
        owner_user_id=owner,
        dev_guild_id=_int_or_none("DEV_GUILD_ID"),
        log_level=_get("LOG_LEVEL", "INFO").upper() or "INFO",
        database_path=Path(_get("DATABASE_PATH", "data/bot.db") or "data/bot.db"),
        allow_paid_models=_bool("ALLOW_PAID_MODELS", False),
        providers=_load_providers(),
        ai_max_calls_per_minute=_int("AI_MAX_CALLS_PER_MINUTE", 20),
        ai_daily_call_limit=_int("AI_DAILY_CALL_LIMIT", 800),
        ai_user_cooldown_seconds=_int("AI_USER_COOLDOWN_SECONDS", 8),
        background_daily_call_limit=_int("BACKGROUND_DAILY_CALL_LIMIT", 150),
        history_daily_call_limit=_int("HISTORY_DAILY_CALL_LIMIT", 250),
    )


def secret_values(settings: Settings) -> list[str]:
    """Everything that must never appear in logs."""
    return [settings.discord_token] + [p.api_key for p in settings.providers if p.name != "ollama"]
