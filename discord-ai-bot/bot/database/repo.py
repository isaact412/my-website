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
