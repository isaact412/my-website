"""Database tables.

Discord IDs ("snowflakes") are used directly as primary keys, so a member's
data stays attached to them even when they change their name.

Changing anything here needs a new migration in migrations/versions/.
"""
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint
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


class Message(Base):
    """A stored Discord message, used for search, stats, recaps and (later) memory.

    Never stored: messages from excluded channels, opted-out users, bots, or DMs.
    Deleting a message in Discord deletes it here too.
    Full-text search lives in the messages_fts table (created in migration 0002).
    """

    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_guild_channel_created", "guild_id", "channel_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Discord message ID
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"))
    channel_id: Mapped[int] = mapped_column(BigInteger)
    author_id: Mapped[int] = mapped_column(BigInteger, index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    reply_to_id: Mapped[int | None] = mapped_column(BigInteger)
    attachment_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Memory(Base):
    """Something the bot remembers: a member fact, a piece of server lore, or a relationship.

    Memories strengthen when the same thing keeps coming up (times_reinforced, distinct_days)
    and fade over time based on their tier. See bot/memory/strength.py.
    """

    __tablename__ = "memories"
    __table_args__ = (Index("ix_memories_guild_kind", "guild_id", "kind", "active"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))  # "member" | "lore" | "relationship"
    subject_ids: Mapped[str] = mapped_column(String(200), default="")  # space-separated user IDs, e.g. " 123 456 "
    title: Mapped[str] = mapped_column(String(120), default="")
    text: Mapped[str] = mapped_column(Text)
    keywords: Mapped[str] = mapped_column(String(300), default="")
    importance: Mapped[int] = mapped_column(Integer, default=1)  # 1 minor, 2 notable, 3 legendary
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    times_reinforced: Mapped[int] = mapped_column(Integer, default=1)
    distinct_days: Mapped[int] = mapped_column(Integer, default=1)
    last_seen_day: Mapped[str] = mapped_column(String(10), default="")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)  # added on purpose via /remember
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary)  # float16 vector, None if embeddings are off
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_referenced: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MemorySource(Base):
    """Which Discord message(s) a memory came from. Powers /whyremember."""

    __tablename__ = "memory_sources"

    memory_id: Mapped[int] = mapped_column(Integer, ForeignKey("memories.id", ondelete="CASCADE"), primary_key=True)
    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    channel_id: Mapped[int] = mapped_column(BigInteger)
    author_id: Mapped[int] = mapped_column(BigInteger, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ScanJob(Base):
    """A /scanserver run. Survives restarts: a running job resumes when the bot starts."""

    __tablename__ = "scan_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20))  # running | paused | done | stopped
    phase: Mapped[str] = mapped_column(String(20), default="fetch")  # fetch → digest → done
    started_by: Mapped[int] = mapped_column(BigInteger)
    progress_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    progress_message_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScanChannel(Base):
    """Per-channel progress for a scan. The cursors make scanning resumable."""

    __tablename__ = "scan_channels"

    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("scan_jobs.id", ondelete="CASCADE"), primary_key=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), default="")
    estimate: Mapped[int] = mapped_column(Integer, default=0)
    fetched: Mapped[int] = mapped_column(Integer, default=0)
    fetch_cursor: Mapped[int] = mapped_column(BigInteger, default=0)   # last message ID read from Discord
    fetch_done: Mapped[bool] = mapped_column(Boolean, default=False)
    digest_cursor: Mapped[int] = mapped_column(BigInteger, default=0)  # last message ID analyzed for memories
    digested: Mapped[int] = mapped_column(Integer, default=0)
    digest_done: Mapped[bool] = mapped_column(Boolean, default=False)
