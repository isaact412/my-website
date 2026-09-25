# Installs/updates the bot files in ~/discord-ai-bot. Never touches your token.
cd ~/discord-ai-bot || exit 1
cat > .env.example <<'EOF_FILE'
DISCORD_TOKEN=
OWNER_USER_ID=819246808671977482
DEV_GUILD_ID=1203498616560295946
LOG_LEVEL=INFO
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
cat > alembic.ini <<'EOF_FILE'
# Alembic settings. The bot runs migrations automatically on startup,
# so you normally never need to touch this file.
[alembic]
script_location = migrations
prepend_sys_path = .
sqlalchemy.url = sqlite:///data/bot.db

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARNING
handlers = console

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
EOF_FILE
mkdir -p bot
cat > bot/__init__.py <<'EOF_FILE'
EOF_FILE
mkdir -p bot/commands
cat > bot/commands/__init__.py <<'EOF_FILE'
EOF_FILE
mkdir -p bot/commands
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
mkdir -p bot/commands
cat > bot/commands/owner.py <<'EOF_FILE'
"""Developer-only commands. Only OWNER_USER_ID from .env can use these."""
import logging
import platform
import time

import discord
from discord import app_commands
from discord.ext import commands

from bot.database import repo

log = logging.getLogger("bot.commands")


def is_owner():
    """Server-side check: hiding a command in Discord's menu is not security, this is."""

    async def predicate(interaction: discord.Interaction) -> bool:
        return interaction.user.id == interaction.client.settings.owner_user_id

    return app_commands.check(predicate)


class Owner(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="debug", description="(bot owner only) show bot health")
    @is_owner()
    async def debug(self, interaction: discord.Interaction) -> None:
        async with self.bot.db.session() as s:
            counts = await repo.count_rows(s)

        uptime_min = int((time.monotonic() - self.bot.started_at) // 60)
        lines = [
            "**debug**",
            f"latency: {round(self.bot.latency * 1000)}ms",
            f"uptime: {uptime_min} min",
            f"servers connected: {len(self.bot.guilds)}",
            f"database: `{self.bot.db.path}` (schema {self.bot.schema_version})",
            f"rows: {counts['guilds']} guilds, {counts['users']} users",
            f"python {platform.python_version()} · discord.py {discord.__version__}",
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @debug.error
    async def debug_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.CheckFailure):
            await interaction.response.send_message("nice try", ephemeral=True)
            log.info("Blocked /debug from non-owner %s", interaction.user.id)
        else:
            log.exception("/debug failed", exc_info=error)
            if not interaction.response.is_done():
                await interaction.response.send_message("debug broke. check the logs.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Owner(bot))
EOF_FILE
mkdir -p bot
cat > bot/config.py <<'EOF_FILE'
"""Loads settings from the .env file and checks they look sane."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


class ConfigError(Exception):
    """Raised when .env is missing something important."""


@dataclass(frozen=True)
class Settings:
    discord_token: str
    owner_user_id: int
    dev_guild_id: int | None
    log_level: str
    database_path: Path


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
        database_path=Path(os.getenv("DATABASE_PATH", "data/bot.db").strip() or "data/bot.db"),
    )
EOF_FILE
mkdir -p bot/database
cat > bot/database/__init__.py <<'EOF_FILE'
EOF_FILE
mkdir -p bot/database
cat > bot/database/engine.py <<'EOF_FILE'
"""Async database connection (SQLite via aiosqlite)."""
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{path}")

        @event.listens_for(self.engine.sync_engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")    # readers don't block the writer
            cur.execute("PRAGMA busy_timeout=5000")   # wait up to 5s instead of "database is locked"
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Use as:  async with db.session() as s: ...   (commits on success, rolls back on error)"""
        async with self._sessions() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    async def close(self) -> None:
        await self.engine.dispose()
EOF_FILE
mkdir -p bot/database
cat > bot/database/migrate.py <<'EOF_FILE'
"""Brings the database schema up to date on startup, backing it up first."""
import logging
import shutil
from datetime import datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

log = logging.getLogger("bot.db")

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config(db_path: Path) -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def current_revision(db_path: Path) -> str | None:
    if not db_path.exists():
        return None
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            return MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()


def upgrade_to_latest(db_path: Path) -> str:
    """Runs any pending migrations. Returns the schema version now in use."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = _alembic_config(db_path)
    head = ScriptDirectory.from_config(cfg).get_current_head()
    current = current_revision(db_path)

    if current == head:
        log.info("Database schema up to date (version %s)", head)
        return head

    if db_path.exists() and current is not None:
        backup_dir = db_path.parent / "backups"
        backup_dir.mkdir(exist_ok=True)
        backup = backup_dir / f"{db_path.stem}-{datetime.now():%Y%m%d-%H%M%S}.db"
        shutil.copy2(db_path, backup)
        log.info("Backed up database to %s before migrating", backup)

    log.info("Migrating database: %s -> %s", current or "empty", head)
    command.upgrade(cfg, "head")
    return head
EOF_FILE
mkdir -p bot/database
cat > bot/database/models.py <<'EOF_FILE'
"""Database tables.

Discord IDs ("snowflakes") are used directly as primary keys, so a member's
data stays attached to them even when they change their name.

Changing anything here needs a new migration in migrations/versions/.
"""
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Guild(Base):
    """A Discord server the bot is in."""

    __tablename__ = "guilds"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    """A Discord account. Server-specific nicknames live in user_names."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String(100))
    global_name: Mapped[str | None] = mapped_column(String(100))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserName(Base):
    """Every name a user has been seen with: username, display name, or server nickname."""

    __tablename__ = "user_names"
    __table_args__ = (UniqueConstraint("user_id", "guild_id", "kind", "value"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, default=0)  # 0 = not server-specific
    kind: Mapped[str] = mapped_column(String(20))  # "username" | "global_name" | "nickname"
    value: Mapped[str] = mapped_column(String(100))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GuildSettings(Base):
    """Per-server bot settings changed through admin commands."""

    __tablename__ = "guild_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True)
    chattiness: Mapped[int] = mapped_column(Integer, default=3)
    roast_level: Mapped[int] = mapped_column(Integer, default=5)
    personality_json: Mapped[str] = mapped_column(Text, default="{}")  # slider overrides
    bot_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    memory_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChannelSetting(Base):
    """Channels an admin has excluded from analysis."""

    __tablename__ = "channel_settings"

    channel_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), index=True)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserSetting(Base):
    """Per-user privacy choices, per server."""

    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    opted_out: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UsageStat(Base):
    """Daily counters for /usage. One row per day + server + provider + model + kind."""

    __tablename__ = "usage_stats"

    day: Mapped[str] = mapped_column(String(10), primary_key=True)  # "2026-09-25"
    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # 0 = not server-specific
    provider: Mapped[str] = mapped_column(String(40), primary_key=True)
    model: Mapped[str] = mapped_column(String(120), primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), primary_key=True)  # "reply" | "background" | "embedding"
    calls: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    rate_limited: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    paid_calls: Mapped[int] = mapped_column(Integer, default=0)
    est_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
EOF_FILE
mkdir -p bot/database
cat > bot/database/repo.py <<'EOF_FILE'
"""Small, safe database helpers. All queries are parameterized by SQLAlchemy."""
import discord
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Guild, GuildSettings, User, utcnow


async def upsert_guild(s: AsyncSession, guild: discord.Guild) -> None:
    """Records a server (and default settings) the first time we see it; refreshes its name after."""
    now = utcnow()
    await s.execute(
        insert(Guild)
        .values(id=guild.id, name=guild.name, first_seen=now, last_seen=now)
        .on_conflict_do_update(index_elements=[Guild.id], set_={"name": guild.name, "last_seen": now})
    )
    await s.execute(insert(GuildSettings).values(guild_id=guild.id).on_conflict_do_nothing())


async def count_rows(s: AsyncSession) -> dict[str, int]:
    return {
        "guilds": await s.scalar(select(func.count()).select_from(Guild)),
        "users": await s.scalar(select(func.count()).select_from(User)),
    }
EOF_FILE
mkdir -p bot
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
    logging.getLogger("alembic").setLevel(logging.WARNING)  # bot.db logs the migration summary instead
EOF_FILE
mkdir -p bot
cat > bot/main.py <<'EOF_FILE'
"""Starts the bot. Run with:  python -m bot.main"""
import logging
import sys
import time

import discord
from discord.ext import commands

from bot.config import ConfigError, Settings, load_settings
from bot.database import repo
from bot.database.engine import Database
from bot.database.migrate import upgrade_to_latest
from bot.logging_setup import setup_logging

log = logging.getLogger("bot")

# Feature modules ("cogs") to load at startup. We add to this list each phase.
EXTENSIONS = [
    "bot.commands.general",
    "bot.commands.owner",
]


class DiscordAIBot(commands.Bot):
    def __init__(self, settings: Settings, db: Database, schema_version: str):
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
        self.db = db
        self.schema_version = schema_version
        self.started_at = time.monotonic()

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
            await self._remember_guild(guild)
            log.info("In server: %s (id %s)", guild.name, guild.id)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        log.info("Joined new server: %s (id %s)", guild.name, guild.id)
        await self._remember_guild(guild)

    async def _remember_guild(self, guild: discord.Guild) -> None:
        try:
            async with self.db.session() as s:
                await repo.upsert_guild(s, guild)
        except Exception:
            # A database hiccup should never take the bot down.
            log.exception("Could not save server %s to the database", guild.id)

    async def close(self) -> None:
        await super().close()
        await self.db.close()


def main() -> None:
    try:
        settings = load_settings()
    except ConfigError as e:
        print(f"[CONFIG ERROR] {e}")
        sys.exit(1)

    setup_logging(settings.log_level, secrets=[settings.discord_token])

    try:
        schema_version = upgrade_to_latest(settings.database_path)
    except Exception:
        log.exception("Database migration failed. Your data was backed up in data/backups/ if it existed.")
        sys.exit(1)

    bot = DiscordAIBot(settings, Database(settings.database_path), schema_version)

    try:
        bot.run(settings.discord_token, log_handler=None)
    except discord.LoginFailure:
        log.error("Discord rejected the token. Reset it in the Developer Portal and paste the new one into .env.")
    except discord.PrivilegedIntentsRequired:
        log.error("Turn ON 'Server Members Intent' and 'Message Content Intent' in the Developer Portal → Bot, then Save.")


if __name__ == "__main__":
    main()
EOF_FILE
mkdir -p migrations
cat > migrations/env.py <<'EOF_FILE'
"""Alembic migration runner (synchronous SQLite connection)."""
from alembic import context
from sqlalchemy import engine_from_config, pool

from bot.database.models import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_online() -> None:
    engine = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with engine.connect() as connection:
        # render_as_batch lets future migrations alter columns on SQLite
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
EOF_FILE
mkdir -p migrations
cat > migrations/script.py.mako <<'EOF_FILE'
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
EOF_FILE
mkdir -p migrations/versions
cat > migrations/versions/0001_initial.py <<'EOF_FILE'
"""initial tables: guilds, users, names, settings, usage

Revision ID: 0001
Revises:
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "guilds",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("first_seen", TS, nullable=False),
        sa.Column("last_seen", TS, nullable=False),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("global_name", sa.String(100), nullable=True),
        sa.Column("first_seen", TS, nullable=False),
        sa.Column("last_seen", TS, nullable=False),
    )
    op.create_table(
        "user_names",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("value", sa.String(100), nullable=False),
        sa.Column("first_seen", TS, nullable=False),
        sa.Column("last_seen", TS, nullable=False),
        sa.UniqueConstraint("user_id", "guild_id", "kind", "value"),
    )
    op.create_index("ix_user_names_user_id", "user_names", ["user_id"])
    op.create_table(
        "guild_settings",
        sa.Column("guild_id", sa.BigInteger(), sa.ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("chattiness", sa.Integer(), nullable=False),
        sa.Column("roast_level", sa.Integer(), nullable=False),
        sa.Column("personality_json", sa.Text(), nullable=False),
        sa.Column("bot_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("memory_enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_table(
        "channel_settings",
        sa.Column("channel_id", sa.BigInteger(), primary_key=True),
        sa.Column("guild_id", sa.BigInteger(), sa.ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("excluded", sa.Boolean(), nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_index("ix_channel_settings_guild_id", "channel_settings", ["guild_id"])
    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.BigInteger(), primary_key=True),
        sa.Column("guild_id", sa.BigInteger(), primary_key=True),
        sa.Column("opted_out", sa.Boolean(), nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_table(
        "usage_stats",
        sa.Column("day", sa.String(10), primary_key=True),
        sa.Column("guild_id", sa.BigInteger(), primary_key=True),
        sa.Column("provider", sa.String(40), primary_key=True),
        sa.Column("model", sa.String(120), primary_key=True),
        sa.Column("kind", sa.String(30), primary_key=True),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("rate_limited", sa.Integer(), nullable=False),
        sa.Column("errors", sa.Integer(), nullable=False),
        sa.Column("paid_calls", sa.Integer(), nullable=False),
        sa.Column("est_cost_usd", sa.Float(), nullable=False),
    )


def downgrade() -> None:
    for table in ("usage_stats", "user_settings", "channel_settings", "guild_settings", "user_names", "users", "guilds"):
        op.drop_table(table)
EOF_FILE
cat > requirements.txt <<'EOF_FILE'
discord.py>=2.7,<3
python-dotenv>=1.0
SQLAlchemy[asyncio]>=2.0,<3
aiosqlite>=0.20
alembic>=1.13
EOF_FILE
touch .env; grep -q '^DISCORD_TOKEN=' .env || echo 'DISCORD_TOKEN=' >> .env
grep -q '^OWNER_USER_ID=' .env || echo 'OWNER_USER_ID=819246808671977482' >> .env
grep -q '^DEV_GUILD_ID=' .env || echo 'DEV_GUILD_ID=1203498616560295946' >> .env
grep -q '^LOG_LEVEL=' .env || echo 'LOG_LEVEL=INFO' >> .env
if grep -qE '^DISCORD_TOKEN=.+' .env; then echo "✅ files updated, token kept"; else echo "⚠️  token missing: paste it after DISCORD_TOKEN= in .env, save, then run: python -m bot.main"; fi
source .venv/bin/activate && pip install -q --disable-pip-version-check -r requirements.txt && python -m bot.main
