"""Decides when the bot joins a conversation it wasn't invited into, and when it just reacts.

Everything here is free: it runs on every message without any AI call. The AI is only asked
once this code decides speaking is worth it, and even then the AI may choose to [skip].
"""
import asyncio
import logging
import random
import re
import time
from collections import defaultdict, deque

import discord
from sqlalchemy import select

from bot.database.models import Memory
from bot.services.reactions import pick_reaction

log = logging.getLogger("bot.decision")

# /chattiness level → (base chance to consider a message, max spontaneous replies per channel per hour)
CHATTINESS = {
    0: (0.0, 0), 1: (0.004, 1), 2: (0.01, 2), 3: (0.025, 3), 4: (0.04, 4), 5: (0.07, 6),
    6: (0.1, 8), 7: (0.14, 10), 8: (0.2, 12), 9: (0.27, 15), 10: (0.35, 20),
}
MIN_GAP_SECONDS = 45            # never two spontaneous replies in a channel closer than this
REACTION_GAP_SECONDS = 90       # at most one reaction per channel in this window
QUESTION_WAIT_SECONDS = 60      # how long a question has to go unanswered
LORE_REFRESH_SECONDS = 600

SERIOUS = re.compile(
    r"\b(died|passed away|funeral|hospital|cancer|depress\w*|suicid\w*|self[- ]harm|break ?up|broke up|"
    r"divorce|not okay|i'?m not ok|panic attack|serious(ly)? though|need help|abuse\w*)\b", re.I)
LAUGHS = re.compile(r"lmao|lmfao|\blol\b|haha|💀|😭|😂", re.I)


class ParticipationEngine:
    def __init__(self, bot):
        self.bot = bot
        self._recent: dict[int, deque] = defaultdict(lambda: deque(maxlen=30))  # channel → (time, author_id, is_me, text)
        self._spoke: dict[int, deque] = defaultdict(lambda: deque(maxlen=50))   # channel → times the bot spoke on its own
        self._last_reaction: dict[int, float] = {}
        self._lore_words: dict[int, set[str]] = {}
        self._lore_loaded: dict[int, float] = {}
        self._pending_questions: dict[int, asyncio.Task] = {}

    def observe(self, message: discord.Message) -> None:
        """Called for every message in a channel the bot is allowed in (including its own)."""
        self._recent[message.channel.id].append(
            (time.monotonic(), message.author.id, message.author.id == self.bot.user.id, message.content or ""))
        # A human reply cancels a pending "nobody answered this question" check in that channel.
        task = self._pending_questions.get(message.channel.id)
        if task and not message.author.bot and not task.done() and getattr(task, "asker", None) != message.author.id:
            task.cancel()

    def note_bot_spoke(self, channel_id: int) -> None:
        self._spoke[channel_id].append(time.monotonic())

    async def consider(self, message: discord.Message) -> None:
        """A message nobody addressed to the bot. Maybe react, maybe reply, usually nothing."""
        cfg = await self.bot.guild_config.get(message.guild.id)
        personality = self.bot.personality.with_overrides(cfg.overrides)
        text = message.content or ""
        if SERIOUS.search(text):
            return  # read the room

        await self._maybe_react(message, personality.level("reactions"))

        base, per_hour = CHATTINESS.get(cfg.chattiness, CHATTINESS[3])
        if cfg.chattiness == 0 or not self._under_limits(message.channel.id, per_hour):
            return

        if text.rstrip().endswith("?") and len(text.split()) >= 3:
            self._watch_question(message, base)

        score = await self.score(message)
        chance = min(0.9, base * (1 + max(score, 0))) if score >= 0 else base * 0.2
        if random.random() < chance:
            log.info("[DECIDE] joining in #%s (score %.1f, chance %.0f%%)", message.channel.name, score, chance * 100)
            await self._speak(message)

    async def score(self, message: discord.Message) -> float:
        """Higher = better moment to chime in. Negative = stay out of it."""
        text = (message.content or "").lower()
        me = message.guild.me
        now = time.monotonic()
        recent = [r for r in self._recent[message.channel.id] if now - r[0] < 600]
        s = 0.0
        if me.display_name.lower() in text or re.search(r"\bthe bot\b|\bbot\b", text):
            s += 4  # people are talking about the bot
        if await self._hits_lore(message.guild.id, text):
            s += 3
        if sum(1 for r in recent[-6:] if LAUGHS.search(r[3])) >= 2:
            s += 1.5  # the chat is having fun
        if any(r[2] for r in recent[-8:]):
            s += 1    # the bot is already part of this conversation
        spoke = [t for t in self._spoke[message.channel.id] if now - t < 900]
        if spoke and now - spoke[-1] < 120:
            s -= 3
        if len(spoke) >= 3:
            s -= 4
        if len({r[1] for r in recent if not r[2]}) >= 4:
            s -= 1    # busy chat with lots of people; don't crowd it
        if len(text.split()) <= 2:
            s -= 1
        return s

    def _under_limits(self, channel_id: int, per_hour: int) -> bool:
        now = time.monotonic()
        spoke = [t for t in self._spoke[channel_id] if now - t < 3600]
        if len(spoke) >= per_hour:
            return False
        return not spoke or now - spoke[-1] >= MIN_GAP_SECONDS

    async def _maybe_react(self, message: discord.Message, level: int) -> None:
        if level == 0 or time.monotonic() - self._last_reaction.get(message.channel.id, -1e9) < REACTION_GAP_SECONDS:
            return
        emoji = pick_reaction(message.content or "")
        if emoji and random.random() < level / 10 * 0.25:
            self._last_reaction[message.channel.id] = time.monotonic()
            try:
                await message.add_reaction(emoji)
                log.info("[DECIDE] reacted %s in #%s", emoji, message.channel.name)
            except discord.HTTPException:
                pass

    def _watch_question(self, message: discord.Message, base: float) -> None:
        old = self._pending_questions.get(message.channel.id)
        if old and not old.done():
            old.cancel()

        async def wait_then_answer():
            await asyncio.sleep(QUESTION_WAIT_SECONDS)
            cfg = await self.bot.guild_config.get(message.guild.id)
            _, per_hour = CHATTINESS.get(cfg.chattiness, CHATTINESS[3])
            if self._under_limits(message.channel.id, per_hour) and random.random() < min(0.8, base * 8):
                log.info("[DECIDE] answering an ignored question in #%s", message.channel.name)
                await self._speak(message)

        task = asyncio.create_task(wait_then_answer())
        task.asker = message.author.id
        self._pending_questions[message.channel.id] = task

    async def _speak(self, message: discord.Message) -> None:
        self.note_bot_spoke(message.channel.id)
        try:
            await self.bot.responder.reply_to(message, spontaneous=True)
        except Exception:
            log.exception("Spontaneous reply failed")

    async def _hits_lore(self, guild_id: int, text: str) -> bool:
        if time.monotonic() - self._lore_loaded.get(guild_id, -1e9) > LORE_REFRESH_SECONDS:
            async with self.bot.db.session() as s:
                rows = await s.execute(select(Memory.title, Memory.keywords).where(
                    Memory.guild_id == guild_id, Memory.kind == "lore", Memory.active.is_(True),
                    Memory.times_reinforced >= 2))
            words = set()
            for title, keywords in rows:
                words |= {w for w in (title + " " + keywords).lower().split() if len(w) >= 5}
            self._lore_words[guild_id] = words
            self._lore_loaded[guild_id] = time.monotonic()
        return bool(set(re.findall(r"\w+", text)) & self._lore_words.get(guild_id, set()))
