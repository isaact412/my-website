"""Voice samples: real messages that show the AI how people in this server actually talk.

Facts alone make the bot sound like an AI describing the server. Real examples make it sound like
the server. Everything here is local SQL, no AI. Only public channels are used.
"""
import random
import re
import time

from sqlalchemy import func, select

from bot.database.models import Message

PER_PERSON = 6
SERVER_HITS = 10
REFRESH_SECONDS = 6 * 3600
_LAUGH = re.compile(r"lmao|lmfao|\blol\b|haha|💀|😭|😂|\bdead\b|crying|bro what", re.I)
_SKIP = re.compile(r"https?://|^/|^<[@#:]|^!", re.I)


def _usable(text: str) -> bool:
    words = len(text.split())
    return 2 <= words <= 25 and not _SKIP.search(text.strip())


class VoiceSampler:
    def __init__(self):
        self._hits: dict[int, list[str]] = {}
        self._loaded: dict[int, float] = {}

    async def samples(self, s, guild_id: int, participant_ids: list[int], public_channels: set[int],
                      names) -> dict[str, list[str]]:
        """{"people": ["name: text", ...], "hits": ["name: text", ...]}"""
        if not public_channels:
            return {"people": [], "hits": []}
        people = []
        for uid in participant_ids[:5]:
            rows = await s.execute(
                select(Message.content).where(
                    Message.guild_id == guild_id, Message.author_id == uid,
                    Message.channel_id.in_(public_channels), func.length(Message.content).between(6, 160))
                .order_by(func.random()).limit(PER_PERSON * 4))
            lines = [t for (t,) in rows if _usable(t)][:PER_PERSON]
            people += [f"{names(uid)}: {t}" for t in lines]
        await self._refresh_hits(s, guild_id, public_channels, names)
        hits = self._hits.get(guild_id, [])
        return {"people": people, "hits": random.sample(hits, min(SERVER_HITS, len(hits)))}

    async def _refresh_hits(self, s, guild_id: int, public_channels: set[int], names) -> None:
        """Every few hours: find messages that got a laugh (someone laughed within the next 3 messages)."""
        if time.monotonic() - self._loaded.get(guild_id, -1e9) < REFRESH_SECONDS:
            return
        result = await s.stream(
            select(Message.channel_id, Message.author_id, Message.content)
            .where(Message.guild_id == guild_id, Message.channel_id.in_(public_channels))
            .order_by(Message.channel_id, Message.id))
        window, hits = [], []
        async for channel_id, author_id, content in result:
            window.append((channel_id, author_id, content or ""))
            if len(window) > 4:
                window.pop(0)
            if len(window) == 4:
                ch, au, text = window[0]
                after = window[1:]
                if (_usable(text) and not _LAUGH.search(text)
                        and all(c == ch for c, _, _ in after)
                        and any(_LAUGH.search(t) and a != au for _, a, t in after)):
                    hits.append((au, text))
        picked = random.sample(hits, min(400, len(hits)))
        self._hits[guild_id] = [f"{names(au)}: {text}" for au, text in picked]
        self._loaded[guild_id] = time.monotonic()
