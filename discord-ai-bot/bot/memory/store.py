"""Database access for memories."""
import random
from datetime import date

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Memory, MemorySource, utcnow


def subject_str(ids) -> str:
    return " " + " ".join(str(i) for i in sorted(set(ids))) + " " if ids else ""


def subject_ids(m: Memory) -> list[int]:
    return [int(x) for x in m.subject_ids.split()]


def _about(user_id: int):
    return Memory.subject_ids.contains(f" {user_id} ")


async def active_memories(s: AsyncSession, guild_id: int, kinds: tuple[str, ...] | None = None) -> list[Memory]:
    stmt = select(Memory).where(Memory.guild_id == guild_id, Memory.active.is_(True))
    if kinds:
        stmt = stmt.where(Memory.kind.in_(kinds))
    return list(await s.scalars(stmt))


async def add_memory(s: AsyncSession, **fields) -> Memory:
    m = Memory(**fields)
    s.add(m)
    await s.flush()  # assigns m.id
    return m


async def reinforce(s: AsyncSession, m: Memory, importance: int, keywords: str) -> None:
    today = date.today().isoformat()
    if m.last_seen_day != today:
        m.distinct_days += 1
        m.last_seen_day = today
    m.times_reinforced += 1
    m.confidence = min(0.95, m.confidence + 0.1)
    m.importance = max(m.importance, importance)
    merged = {k for k in (m.keywords + " " + keywords).split() if k}
    m.keywords = " ".join(sorted(merged))[:300]
    m.updated_at = utcnow()


async def add_sources(s: AsyncSession, memory_id: int, messages) -> None:
    """messages: stored Message rows (or anything with id/channel_id/author_id/created_at)."""
    existing = set(await s.scalars(select(MemorySource.message_id).where(MemorySource.memory_id == memory_id)))
    for msg in messages:
        if msg.id not in existing:
            existing.add(msg.id)  # the AI sometimes cites the same message twice
            s.add(MemorySource(memory_id=memory_id, message_id=msg.id, channel_id=msg.channel_id,
                               author_id=msg.author_id, created_at=msg.created_at))


async def sources(s: AsyncSession, memory_id: int) -> list[MemorySource]:
    return list(await s.scalars(
        select(MemorySource).where(MemorySource.memory_id == memory_id).order_by(MemorySource.created_at)
    ))


async def about_user(s: AsyncSession, guild_id: int, user_id: int) -> list[Memory]:
    return list(await s.scalars(
        select(Memory).where(Memory.guild_id == guild_id, Memory.active.is_(True), _about(user_id))
        .order_by(Memory.times_reinforced.desc())
    ))


async def get(s: AsyncSession, guild_id: int, memory_id: int) -> Memory | None:
    return await s.scalar(select(Memory).where(Memory.id == memory_id, Memory.guild_id == guild_id))


async def delete_memory(s: AsyncSession, memory_id: int) -> None:
    await s.execute(delete(MemorySource).where(MemorySource.memory_id == memory_id))
    await s.execute(delete(Memory).where(Memory.id == memory_id))


async def mark_referenced(s: AsyncSession, ids: list[int]) -> None:
    if ids:
        await s.execute(update(Memory).where(Memory.id.in_(ids)).values(last_referenced=utcnow()))


async def random_lore(s: AsyncSession, guild_id: int, n: int = 3) -> list[Memory]:
    rows = list(await s.scalars(select(Memory).where(
        Memory.guild_id == guild_id, Memory.kind == "lore", Memory.active.is_(True))))
    return random.sample(rows, min(n, len(rows)))


async def forget_user_memories(s: AsyncSession, guild_id: int, user_id: int) -> int:
    """Deletes memories about the user, and memories built only from their messages."""
    ids = set(await s.scalars(select(Memory.id).where(Memory.guild_id == guild_id, _about(user_id))))
    only_theirs = await s.execute(
        select(MemorySource.memory_id)
        .join(Memory, Memory.id == MemorySource.memory_id)
        .where(Memory.guild_id == guild_id)
        .group_by(MemorySource.memory_id)
        .having(func.sum(MemorySource.author_id != user_id) == 0)
    )
    ids |= set(only_theirs.scalars())
    for mid in ids:
        await delete_memory(s, mid)
    # Their messages no longer count as evidence for shared memories either.
    await s.execute(delete(MemorySource).where(
        MemorySource.author_id == user_id,
        MemorySource.memory_id.in_(select(Memory.id).where(Memory.guild_id == guild_id)),
    ))
    return len(ids)


async def forget_channel_memories(s: AsyncSession, guild_id: int, channel_id: int) -> int:
    """Removes a channel's evidence; memories left with no evidence (and not added on purpose) are deleted."""
    await s.execute(delete(MemorySource).where(
        MemorySource.channel_id == channel_id,
        MemorySource.memory_id.in_(select(Memory.id).where(Memory.guild_id == guild_id)),
    ))
    orphans = list(await s.scalars(select(Memory.id).where(
        Memory.guild_id == guild_id, Memory.pinned.is_(False),
        ~Memory.id.in_(select(MemorySource.memory_id)),
    )))
    for mid in orphans:
        await delete_memory(s, mid)
    return len(orphans)


async def clear_guild(s: AsyncSession, guild_id: int) -> int:
    ids = list(await s.scalars(select(Memory.id).where(Memory.guild_id == guild_id)))
    await s.execute(delete(MemorySource).where(MemorySource.memory_id.in_(ids)))
    await s.execute(delete(Memory).where(Memory.guild_id == guild_id))
    return len(ids)


def matches_keywords(m: Memory, words: set[str]) -> float:
    """Fallback relevance when embeddings are off: share of memory keywords/title words found."""
    mem_words = set((m.keywords + " " + m.title + " " + m.text).lower().split())
    return len(mem_words & words) / (len(words) or 1)


def search_filter(term: str):
    like = f"%{term.lower()}%"
    return or_(func.lower(Memory.text).like(like), func.lower(Memory.title).like(like), func.lower(Memory.keywords).like(like))


async def purge_sensitive(s: AsyncSession) -> int:
    """Deletes any saved memory that the (current) sensitive filter would block. Runs at startup."""
    from bot.memory.sensitive import is_sensitive
    rows = list(await s.execute(select(Memory.id, Memory.title, Memory.text)))
    bad = [mid for mid, title, text in rows if is_sensitive(f"{title} {text}")]
    for mid in bad:
        await delete_memory(s, mid)
    return len(bad)
