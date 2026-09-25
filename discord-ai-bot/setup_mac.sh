cd ~/discord-ai-bot && mkdir -p bot/commands && touch bot/__init__.py bot/commands/__init__.py
cat > bot/config.py <<'EOF_FILE'
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
EOF_FILE
cat > bot/logging_setup.py <<'EOF_FILE'
"""Console + file logging, with secrets scrubbed out of every line."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


class RedactSecrets(logging.Filter):
    """Replaces any secret value with *** before a log line is written."""

    def __init__(self, secrets: list[str]):
        super().__init__()
        self.secrets = [s for s in secrets if s]

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for secret in self.secrets:
            message = message.replace(secret, "***")
        record.msg, record.args = message, None
        return True


def setup_logging(level: str, secrets: list[str]) -> None:
    Path("logs").mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%H:%M:%S")

    console = logging.StreamHandler()
    file = RotatingFileHandler("logs/bot.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")

    root = logging.getLogger()
    root.setLevel(level)
    for handler in (console, file):
        handler.setFormatter(fmt)
        handler.addFilter(RedactSecrets(secrets))
        root.addHandler(handler)

    # discord.py is very chatty at INFO; keep its noise down
    logging.getLogger("discord").setLevel(logging.WARNING)
EOF_FILE
cat > bot/main.py <<'EOF_FILE'
"""Starts the bot. Run with:  python -m bot.main"""
import logging
import sys

import discord
from discord.ext import commands

from bot.config import ConfigError, Settings, load_settings
from bot.logging_setup import setup_logging

log = logging.getLogger("bot")

# Feature modules ("cogs") to load at startup. We add to this list each phase.
EXTENSIONS = [
    "bot.commands.general",
]


class DiscordAIBot(commands.Bot):
    def __init__(self, settings: Settings):
        intents = discord.Intents.default()
        intents.message_content = True  # read message text (enabled in the Developer Portal)
        intents.members = True          # nicknames, joins/leaves (enabled in the Developer Portal)

        super().__init__(
            command_prefix=commands.when_mentioned,  # no "!" commands; we use slash commands
            intents=intents,
            # Never let the bot ping @everyone, @here or roles, whatever it's told to say.
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True, replied_user=True),
        )
        self.settings = settings

    async def setup_hook(self) -> None:
        for ext in EXTENSIONS:
            await self.load_extension(ext)
            log.info("Loaded %s", ext)

        # Syncing to your test server makes slash commands appear instantly.
        if self.settings.dev_guild_id:
            guild = discord.Object(id=self.settings.dev_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d slash command(s) to test server", len(synced))
        else:
            synced = await self.tree.sync()
            log.info("Synced %d global slash command(s) (can take up to an hour to appear)", len(synced))

    async def on_ready(self) -> None:
        log.info("Bot connected as %s (id %s)", self.user, self.user.id)
        for guild in self.guilds:
            log.info("In server: %s (id %s)", guild.name, guild.id)


def main() -> None:
    try:
        settings = load_settings()
    except ConfigError as e:
        print(f"[CONFIG ERROR] {e}")
        sys.exit(1)

    setup_logging(settings.log_level, secrets=[settings.discord_token])
    bot = DiscordAIBot(settings)

    try:
        bot.run(settings.discord_token, log_handler=None)
    except discord.LoginFailure:
        log.error("Discord rejected the token. Reset it in the Developer Portal and paste the new one into .env.")
    except discord.PrivilegedIntentsRequired:
        log.error("Turn ON 'Server Members Intent' and 'Message Content Intent' in the Developer Portal → Bot, then Save.")


if __name__ == "__main__":
    main()
EOF_FILE
cat > bot/commands/general.py <<'EOF_FILE'
"""Basic commands anyone can use."""
import logging

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("bot.commands")


class General(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ping", description="check if the bot is alive")
    async def ping(self, interaction: discord.Interaction) -> None:
        latency_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"pong 🏓 ({latency_ms}ms)")
        log.info("/ping used by %s", interaction.user.id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(General(bot))
EOF_FILE
cat > .gitignore <<'EOF_FILE'
.env
.venv/
venv/
__pycache__/
*.pyc
data/
logs/
.DS_Store
EOF_FILE
cat > requirements.txt <<'EOF_FILE'
discord.py>=2.7,<3
python-dotenv>=1.0
EOF_FILE
touch .env; grep -q '^DISCORD_TOKEN=' .env || echo 'DISCORD_TOKEN=' >> .env
grep -q '^OWNER_USER_ID=' .env || echo 'OWNER_USER_ID=819246808671977482' >> .env
grep -q '^DEV_GUILD_ID=' .env || echo 'DEV_GUILD_ID=1203498616560295946' >> .env
grep -q '^LOG_LEVEL=' .env || echo 'LOG_LEVEL=INFO' >> .env
if grep -qE '^DISCORD_TOKEN=.+' .env; then echo "✅ files written, token kept"; else echo "⚠️  token missing: paste it after DISCORD_TOKEN= in .env, save, then run: python -m bot.main"; fi
source .venv/bin/activate && pip install -q --disable-pip-version-check -r requirements.txt && python -m bot.main
