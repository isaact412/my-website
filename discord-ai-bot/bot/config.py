"""Loads settings from the .env file and checks they look sane."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv


class ConfigError(Exception):
    """Raised when .env is missing something important."""


@dataclass(frozen=True)
class Settings:
    discord_token: str
    owner_user_id: int
    dev_guild_id: int | None
    log_level: str


def _int_or_none(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    if not raw.isdigit():
        raise ConfigError(f"{name} must be a number (a Discord ID), got: {raw!r}")
    return int(raw)


def load_settings() -> Settings:
    load_dotenv()  # reads .env from the folder you run the bot in

    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise ConfigError("DISCORD_TOKEN is empty. Paste your bot token into .env.")

    owner = _int_or_none("OWNER_USER_ID")
    if owner is None:
        raise ConfigError("OWNER_USER_ID is empty. Put your Discord user ID in .env.")

    return Settings(
        discord_token=token,
        owner_user_id=owner,
        dev_guild_id=_int_or_none("DEV_GUILD_ID"),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO",
    )
