"""The reply pipeline: gather context → ask the free AI → clean up → send."""
import logging
import time

import discord

from bot.ai.budget import Budget
from bot.ai.prompts import build_messages, clean_reply
from bot.ai.router import AIRouter, AllProvidersUnavailable
from bot.character.personality import Personality
from bot.database import repo
from bot.database.engine import Database
from bot.memory import store
from bot.memory.embeddings import Embedder
from bot.memory.retrieval import relevant_memories
from bot.services.privacy import PrivacyState

log = logging.getLogger("bot.ai")

HISTORY_MESSAGES = 12
OFFLINE_NOTICE_EVERY = 300  # seconds; don't spam "brain offline" messages


class Responder:
    def __init__(self, bot: discord.Client, router: AIRouter, budget: Budget, db: Database, personality: Personality,
                 embedder: Embedder, privacy: PrivacyState):
        self.bot = bot
        self.router = router
        self.budget = budget
        self.db = db
        self.personality = personality
        self.embedder = embedder
        self.privacy = privacy
        self._last_offline_notice: dict[int, float] = {}

    async def reply_to(self, message: discord.Message) -> None:
        blocked = self.budget.blocked_reason(message.author.id)
        if blocked:
            log.info("[AI] skipped reply to %s: %s", message.author.id, blocked)
            await _safe_react(message, "⏳")
            return

        history, replying_to, participants = await self._context(message)
        me = message.guild.me if message.guild else self.bot.user
        bot_name = me.display_name
        memory_lines = await self._memories(message, history, participants)
        prompt = build_messages(
            self.personality, bot_name, getattr(message.channel, "name", "dm"),
            history, message.author.display_name, message.clean_content, replying_to, memory_lines,
        )

        self.budget.record(message.author.id)
        log.info("[AI] reply requested by %s in #%s", message.author.id, getattr(message.channel, "name", "?"))
        try:
            async with message.channel.typing():
                result = await self.router.chat(prompt, max_tokens=300)
        except AllProvidersUnavailable:
            await self._usage(message, "none", "none", rate_limited=1)
            await self._offline_notice(message)
            return

        text = clean_reply(result.text, bot_name)
        await self._usage(message, result.provider, result.model, calls=1,
                          input_tokens=result.input_tokens, output_tokens=result.output_tokens)
        if not text:
            log.warning("[AI] %s returned an empty reply", result.provider)
            await _safe_react(message, "🤨")
            return
        try:
            await message.reply(text, mention_author=False)
        except discord.HTTPException as e:
            log.warning("Could not send reply: %s", e)

    async def _memories(self, message: discord.Message, history, participants: list[int]) -> dict[str, list[str]]:
        """A few relevant memories about the people talking, plus maybe one callback."""
        try:
            conversation = " ".join(text for _, text in history[-6:]) + " " + message.clean_content
            async with self.db.session() as s:
                found = await relevant_memories(
                    s, self.embedder, message.guild.id, participants, conversation,
                    callback_chance=self.personality.level("callbacks") / 10,
                    opted_out=lambda uid: self.privacy.user_opted_out(message.guild.id, uid),
                )
                await store.mark_referenced(s, [m.id for m in found["lore"]])
        except Exception:
            log.exception("Memory lookup failed; replying without memory")
            return {}
        people = []
        for m in found["people"]:
            names = [self._name(message.guild, uid) for uid in store.subject_ids(m)]
            people.append(f"{' & '.join(names)}: {m.text}")
        lore = [f"{m.title}: {m.text}" if m.title else m.text for m in found["lore"]]
        if people or lore:
            log.info("[MEMORY] using %d people memories, %d lore", len(people), len(lore))
        return {"people": people, "lore": lore}

    @staticmethod
    def _name(guild: discord.Guild, user_id: int) -> str:
        member = guild.get_member(user_id)
        return member.display_name if member else "someone"

    async def _context(self, message: discord.Message):
        """Recent channel messages (oldest first), the message being replied to, and who's talking."""
        history: list[tuple[str, str]] = []
        participants = {message.author.id} | {u.id for u in message.mentions if not u.bot}
        try:
            async for m in message.channel.history(limit=HISTORY_MESSAGES, before=message):
                name = "you" if m.author.id == self.bot.user.id else m.author.display_name
                if not m.author.bot:
                    participants.add(m.author.id)
                if m.clean_content:
                    history.append((name, m.clean_content))
            history.reverse()
        except (discord.Forbidden, discord.HTTPException):
            log.info("No history access in #%s; replying without context", getattr(message.channel, "name", "?"))

        replying_to = None
        ref = message.reference
        if ref and ref.message_id:
            parent = ref.resolved if isinstance(ref.resolved, discord.Message) else None
            if parent is None:
                try:
                    parent = await message.channel.fetch_message(ref.message_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    parent = None  # deleted or not visible; that's fine
            if parent is not None:
                name = "you" if parent.author.id == self.bot.user.id else parent.author.display_name
                replying_to = (name, parent.clean_content)
        return history, replying_to, list(participants)

    async def _offline_notice(self, message: discord.Message) -> None:
        now = time.monotonic()
        channel_id = message.channel.id
        if now - self._last_offline_notice.get(channel_id, -1e9) < OFFLINE_NOTICE_EVERY:
            await _safe_react(message, "💤")
            return
        self._last_offline_notice[channel_id] = now
        try:
            await message.reply("my brain is buffering rn. try again in a bit", mention_author=False)
        except discord.HTTPException:
            pass

    async def _usage(self, message: discord.Message, provider: str, model: str, **counts) -> None:
        try:
            async with self.db.session() as s:
                await repo.record_usage(s, guild_id=message.guild.id if message.guild else 0,
                                        provider=provider, model=model, kind="reply", **counts)
        except Exception:
            log.exception("Could not record usage")


async def _safe_react(message: discord.Message, emoji: str) -> None:
    try:
        await message.add_reaction(emoji)
    except discord.HTTPException:
        pass
