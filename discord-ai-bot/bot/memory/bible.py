"""The server bible: the big-picture context every reply gets.

Retrieval gives the bot scraps (a few facts, a few old messages). The bible gives it the overview:
what this server is, its running jokes and legendary incidents, phrases that only make sense here,
and a short character sheet for each regular. It's written by the background AI (Ollama) from all
saved memories plus stats computed locally over every stored message, and rebuilt every 12 hours.
Saved as data/server_bible_<guild_id>.json (no database changes).
"""
import asyncio
import json
import logging
import re
import time
from collections import Counter, defaultdict
from datetime import timezone
from pathlib import Path

from sqlalchemy import func, select

from bot.ai.prompts import sanitize
from bot.ai.providers.base import ChatMessage
from bot.ai.router import AllProvidersUnavailable
from bot.database.models import Message
from bot.memory import store
from bot.memory.recall import STOPWORDS
from bot.memory.strength import strength

log = logging.getLogger("bot.memory")

REBUILD_SECONDS = 12 * 3600
MAX_MEMBERS = 25          # character sheets for the most-remembered regulars
MIN_MEMORIES = 3
SHEETS_PER_REPLY = 5

GUARDRAILS = ("focus on bits, habits, humor, games, music, running jokes and how they act in the server. "
              "leave out health, sexuality, religion, politics, ethnicity and where anyone lives.")

SHEET_PROMPT = """you write short "character sheets" for a discord bot so it understands the people in a friend server.
write 4-6 short lines, in lowercase group-chat voice, about this person: what they're known for, their running bits,
how they talk (phrases, style), who they're always with, and the best material to tease them with.
only use what's in the notes. no intro, no headings, just the lines. """ + GUARDRAILS

OVERVIEW_PROMPT = """you write the "server bible" for a discord bot so it understands a friend server's culture.
from the notes, write max 250 words in lowercase group-chat voice covering: what this server is about, the biggest
running jokes and legendary incidents (with the names involved), what the recurring phrases mean, who's tight with who,
and the general vibe/humor. be specific, use names. no headings, no intro. """ + GUARDRAILS


def _grams(content: str):
    words = re.findall(r"[a-z0-9']+", (content or "").lower())
    seen = set()
    for n in (2, 3):
        for i in range(len(words) - n + 1):
            gram = words[i:i + n]
            if all(w in STOPWORDS or len(w) < 3 for w in gram):
                continue
            phrase = " ".join(gram)
            if phrase not in seen:
                seen.add(phrase)
                yield phrase


def recurring_phrases(rows, top: int = 30) -> list[str]:
    """2-3 word phrases used by 3+ different people on 3+ different days: the server's own slang/bits.

    Two passes to keep memory low on big servers: count everything, then only track
    who/when for phrases that were common enough.
    """
    counts = Counter()
    for _, _, content in rows:
        counts.update(_grams(content))
    common = {p for p, c in counts.items() if c >= 8}
    del counts
    authors, days, freq = defaultdict(set), defaultdict(set), Counter()
    for author_id, created_at, content in rows:
        day = created_at.date() if created_at else None
        for phrase in _grams(content):
            if phrase in common:
                freq[phrase] += 1
                authors[phrase].add(author_id)
                days[phrase].add(day)
    good = [p for p in common if len(authors[p]) >= 3 and len(days[p]) >= 3]
    good.sort(key=lambda p: freq[p] * len(authors[p]), reverse=True)
    out = []
    for p in good:  # drop phrases contained in an already-picked stronger one
        if not any(p in q or q in p for q in out):
            out.append(p)
        if len(out) >= top:
            break
    return [f"\"{p}\" ({freq[p]}x, {len(authors[p])} people)" for p in out]


class ServerBible:
    def __init__(self, bot, data_dir: Path):
        self.bot = bot
        self.data_dir = data_dir
        self._cache: dict[int, dict] = {}
        self._building: set[int] = set()

    def _path(self, guild_id: int) -> Path:
        return self.data_dir / f"server_bible_{guild_id}.json"

    def get(self, guild_id: int) -> dict:
        if guild_id not in self._cache:
            try:
                self._cache[guild_id] = json.loads(self._path(guild_id).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._cache[guild_id] = {}
        bible = self._cache[guild_id]
        if time.time() - bible.get("built_at", 0) > REBUILD_SECONDS and guild_id not in self._building:
            self._building.add(guild_id)
            asyncio.create_task(self._build(guild_id))
        return bible

    def for_reply(self, guild_id: int, participant_ids: list[int]) -> dict[str, list[str]]:
        bible = self.get(guild_id)
        sheets = bible.get("members", {})
        people = [sheets[str(uid)] for uid in participant_ids if str(uid) in sheets][:SHEETS_PER_REPLY]
        return {"bible_overview": [bible["overview"]] if bible.get("overview") else [], "bible_people": people}

    async def _build(self, guild_id: int) -> None:
        try:
            await self._build_inner(guild_id)
        except Exception:
            log.exception("[BIBLE] build failed; will retry in 12 hours")
            self._cache.setdefault(guild_id, {})["built_at"] = time.time()
        finally:
            self._building.discard(guild_id)

    async def _build_inner(self, guild_id: int) -> None:
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return
        name = lambda uid: guild.get_member(uid).display_name if guild.get_member(uid) else "someone"
        router = self.bot.extractor.router  # the background AI (Ollama when configured)
        log.info("[BIBLE] building the server bible for %s...", guild.name)
        public = {c.id for c in guild.text_channels if c.permissions_for(guild.default_role).read_message_history}

        async with self.bot.db.session() as s:
            memories = await store.active_memories(s, guild_id)
            result = await s.stream(select(Message.author_id, Message.created_at, Message.content)
                                    .where(Message.guild_id == guild_id, Message.channel_id.in_(public)))
            rows = [r async for r in result]
            top_talkers = dict(list(await s.execute(
                select(Message.author_id, func.count()).where(Message.guild_id == guild_id)
                .group_by(Message.author_id).order_by(func.count().desc()).limit(40))))
        phrases = await asyncio.to_thread(recurring_phrases, rows)

        by_person = defaultdict(list)
        for m in memories:
            for uid in store.subject_ids(m):
                by_person[uid].append(m)
        regulars = sorted((uid for uid, ms in by_person.items() if len(ms) >= MIN_MEMORIES and guild.get_member(uid)),
                          key=lambda uid: len(by_person[uid]), reverse=True)[:MAX_MEMBERS]

        sheets = {}
        for uid in regulars:
            notes = sorted(by_person[uid], key=strength, reverse=True)[:25]
            msg_count = top_talkers.get(uid, 0)
            text = "\n".join(f"- {sanitize(m.text)}" for m in notes)
            answer = await self._ask(router, SHEET_PROMPT, f"person: {name(uid)} ({msg_count:,} messages)\nnotes:\n{text}")
            if answer:
                sheets[str(uid)] = f"{name(uid)}: " + " / ".join(l.strip("-• ").strip() for l in answer.splitlines() if l.strip())[:700]

        lore = sorted((m for m in memories if m.kind == "lore"), key=strength, reverse=True)[:40]
        rel = sorted((m for m in memories if m.kind == "relationship"), key=strength, reverse=True)[:15]
        notes = ("legendary lore:\n" + "\n".join(f"- {sanitize((m.title + ': ') if m.title else '')}{sanitize(m.text)}" for m in lore)
                 + "\n\nwho's tight with who:\n" + "\n".join(f"- {sanitize(m.text)}" for m in rel)
                 + "\n\nphrases this server keeps saying:\n" + "\n".join(f"- {p}" for p in phrases)
                 + "\n\nmost active: " + ", ".join(f"{name(u)} ({c:,})" for u, c in list(top_talkers.items())[:12]))
        overview = await self._ask(router, OVERVIEW_PROMPT, notes, max_tokens=700)

        bible = {"built_at": time.time(), "overview": (overview or "")[:2200], "members": sheets, "phrases": phrases}
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._path(guild_id).write_text(json.dumps(bible, ensure_ascii=False, indent=1), encoding="utf-8")
        self._cache[guild_id] = bible
        log.info("[BIBLE] done: overview %d chars, %d character sheets, %d recurring phrases",
                 len(bible["overview"]), len(sheets), len(phrases))

    @staticmethod
    async def _ask(router, system: str, user: str, max_tokens: int = 350) -> str:
        for attempt in range(3):
            try:
                result = await router.chat([ChatMessage("system", system), ChatMessage("user", user)],
                                           max_tokens=max_tokens, temperature=0.6)
                return result.text.strip()
            except AllProvidersUnavailable:
                await asyncio.sleep(60 * (attempt + 1))
        return ""
