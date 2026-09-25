"""Small, safe database helpers. All queries are parameterized by SQLAlchemy."""
import re
from datetime import date

import discord
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import (
    ChannelSetting, Guild, GuildSettings, Message, UsageStat, User, UserName, UserSetting, utcnow,
)


# ---------- servers ----------

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
        "messages": await s.scalar(select(func.count()).select_from(Message)),
    }


# ---------- users and names ----------

async def upsert_user_names(s: AsyncSession, member: discord.Member | discord.User, guild_id: int) -> None:
    """Records the user by ID, plus every name they're seen with (names change, the ID doesn't)."""
    now = utcnow()
    await s.execute(
        insert(User)
        .values(id=member.id, username=member.name, global_name=member.global_name, first_seen=now, last_seen=now)
        .on_conflict_do_update(
            index_elements=[User.id],
            set_={"username": member.name, "global_name": member.global_name, "last_seen": now},
        )
    )
    names = [("username", 0, member.name)]
    if member.global_name:
        names.append(("global_name", 0, member.global_name))
    nick = getattr(member, "nick", None)
    if nick:
        names.append(("nickname", guild_id, nick))
    for kind, gid, value in names:
        await s.execute(
            insert(UserName)
            .values(user_id=member.id, guild_id=gid, kind=kind, value=value[:100], first_seen=now, last_seen=now)
            .on_conflict_do_update(
                index_elements=[UserName.user_id, UserName.guild_id, UserName.kind, UserName.value],
                set_={"last_seen": now},
            )
        )


# ---------- messages ----------

async def store_message(s: AsyncSession, m: discord.Message) -> None:
    ref = m.reference.message_id if m.reference else None
    values = dict(
        id=m.id, guild_id=m.guild.id, channel_id=m.channel.id, author_id=m.author.id,
        content=m.content or "", reply_to_id=ref, attachment_count=len(m.attachments),
        created_at=m.created_at, edited_at=m.edited_at,
    )
    await s.execute(
        insert(Message).values(**values).on_conflict_do_update(
            index_elements=[Message.id], set_={"content": values["content"], "edited_at": values["edited_at"]}
        )
    )


async def update_message_content(s: AsyncSession, message_id: int, content: str) -> None:
    await s.execute(update(Message).where(Message.id == message_id).values(content=content, edited_at=utcnow()))


async def delete_messages(s: AsyncSession, message_ids: list[int]) -> None:
    await s.execute(delete(Message).where(Message.id.in_(message_ids)))


async def delete_channel_messages(s: AsyncSession, channel_id: int) -> int:
    result = await s.execute(delete(Message).where(Message.channel_id == channel_id))
    return result.rowcount or 0


def _fts_query(raw: str) -> str | None:
    """Turns user text into a safe FTS5 query: each word is quoted, so no search syntax gets through."""
    words = re.findall(r"\w+", raw.lower())[:8]
    return " ".join(f'"{w}"' for w in words) or None


async def search_messages(
    s: AsyncSession, guild_id: int, query: str, author_id: int | None, limit: int = 25
) -> list[Message]:
    fts = _fts_query(query)
    if not fts:
        return []
    ids = (await s.execute(
        text("SELECT rowid FROM messages_fts WHERE messages_fts MATCH :q ORDER BY rank LIMIT 500"), {"q": fts}
    )).scalars().all()
    if not ids:
        return []
    stmt = select(Message).where(Message.id.in_(ids), Message.guild_id == guild_id)
    if author_id:
        stmt = stmt.where(Message.author_id == author_id)
    rows = list(await s.scalars(stmt))
    order = {mid: i for i, mid in enumerate(ids)}  # keep FTS relevance order
    return sorted(rows, key=lambda m: order[m.id])[:limit]


# ---------- privacy ----------

async def set_channel_excluded(s: AsyncSession, guild_id: int, channel_id: int, excluded: bool) -> None:
    await s.execute(
        insert(ChannelSetting)
        .values(channel_id=channel_id, guild_id=guild_id, excluded=excluded, updated_at=utcnow())
        .on_conflict_do_update(index_elements=[ChannelSetting.channel_id], set_={"excluded": excluded, "updated_at": utcnow()})
    )


async def set_opted_out(s: AsyncSession, guild_id: int, user_id: int, opted_out: bool) -> None:
    await s.execute(
        insert(UserSetting)
        .values(user_id=user_id, guild_id=guild_id, opted_out=opted_out, updated_at=utcnow())
        .on_conflict_do_update(
            index_elements=[UserSetting.user_id, UserSetting.guild_id], set_={"opted_out": opted_out, "updated_at": utcnow()}
        )
    )


async def what_we_know(s: AsyncSession, guild_id: int, user_id: int) -> dict:
    msg_count = await s.scalar(
        select(func.count()).select_from(Message).where(Message.guild_id == guild_id, Message.author_id == user_id)
    )
    first = await s.scalar(
        select(func.min(Message.created_at)).where(Message.guild_id == guild_id, Message.author_id == user_id)
    )
    names = list(await s.execute(
        select(UserName.kind, UserName.value)
        .where(UserName.user_id == user_id, UserName.guild_id.in_([0, guild_id]))
        .order_by(UserName.first_seen)
    ))
    return {"messages": msg_count or 0, "first_message": first, "names": names}


async def forget_user(s: AsyncSession, guild_id: int, user_id: int) -> int:
    """Deletes everything stored about this user in this server. Returns messages deleted."""
    result = await s.execute(delete(Message).where(Message.guild_id == guild_id, Message.author_id == user_id))
    await s.execute(delete(UserName).where(UserName.user_id == user_id, UserName.guild_id == guild_id))
    # Account-wide names (username/display name) are only kept if they're in another server we know.
    in_other_servers = await s.scalar(
        select(func.count()).select_from(Message).where(Message.author_id == user_id, Message.guild_id != guild_id)
    )
    if not in_other_servers:
        await s.execute(delete(UserName).where(UserName.user_id == user_id))
        await s.execute(delete(User).where(User.id == user_id))
    return result.rowcount or 0


async def clear_guild_memory(s: AsyncSession, guild_id: int) -> int:
    """Deletes all stored messages and nicknames for a server. Settings are kept."""
    result = await s.execute(delete(Message).where(Message.guild_id == guild_id))
    await s.execute(delete(UserName).where(UserName.guild_id == guild_id))
    return result.rowcount or 0


# ---------- usage ----------

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
