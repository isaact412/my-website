"""Small, safe database helpers. All queries are parameterized by SQLAlchemy."""
from datetime import date

import discord
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Guild, GuildSettings, UsageStat, User, utcnow


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


async def record_usage(
    s: AsyncSession, *, guild_id: int, provider: str, model: str, kind: str,
    calls: int = 0, input_tokens: int = 0, output_tokens: int = 0,
    rate_limited: int = 0, errors: int = 0, paid_calls: int = 0, cost: float = 0.0,
) -> None:
    """Adds to today's counters for this server/provider/model/kind."""
    key = dict(day=date.today().isoformat(), guild_id=guild_id, provider=provider, model=model, kind=kind)
    counts = dict(calls=calls, input_tokens=input_tokens, output_tokens=output_tokens,
                  rate_limited=rate_limited, errors=errors, paid_calls=paid_calls, est_cost_usd=cost)
    stmt = insert(UsageStat).values(**key, **counts)
    await s.execute(stmt.on_conflict_do_update(
        index_elements=list(key),
        set_={col: getattr(UsageStat, col) + getattr(stmt.excluded, col) for col in counts},
    ))


async def usage_today(s: AsyncSession, guild_id: int) -> list[UsageStat]:
    rows = await s.scalars(
        select(UsageStat).where(UsageStat.day == date.today().isoformat(), UsageStat.guild_id == guild_id)
    )
    return list(rows)
