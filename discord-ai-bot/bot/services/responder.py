"""The reply pipeline: gather context → ask the free AI → clean up → send."""
import logging
import random
import re
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
from bot.memory.recall import recall_messages
from bot.memory.voice import VoiceSampler
from bot.memory.bible import ServerBible
from bot.character.nicknames import Nicknames
from bot.memory.retrieval import relevant_memories
from bot.services.privacy import PrivacyState

log = logging.getLogger("bot.ai")

HISTORY_MESSAGES = 30      # recent messages the bot reads before replying
RECALL_MESSAGES = 6        # old messages pulled back from the full history
_REACT = re.compile(r"\[react:\s*([^\]]{1,32})\]", re.I)
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
        self.voice = VoiceSampler()
        self.bible = ServerBible(bot, db.path.parent)
        self.nicknames = Nicknames()

    async def personality_for(self, guild_id: int) -> Personality:
        cfg = await self.bot.guild_config.get(guild_id)
        overrides = dict(cfg.overrides)
        overrides.setdefault("roasting", cfg.roast_level)
        return self.personality.with_overrides(overrides)

    async def reply_to(self, message: discord.Message, spontaneous: bool = False, task: str | None = None) -> None:
        """spontaneous=True: nobody asked; the AI may decide to [skip]. task: a special instruction (e.g. /roastme)."""
        blocked = self.budget.blocked_reason(None if spontaneous else message.author.id)
        if blocked:
            log.info("[AI] skipped reply to %s: %s", message.author.id, blocked)
            if not spontaneous:
                await _safe_react(message, "⏳")
            return

        history, replying_to, participants = await self._context(message)
        me = message.guild.me if message.guild else self.bot.user
        bot_name = me.display_name
        memory_lines = await self._memories(message, history, participants)
        if task is None:
            task = ("nobody asked you, you're jumping into the conversation on your own. only say something if it's "
                    "genuinely funny or useful. if you've got nothing good, reply with exactly [skip]."
                    if spontaneous else "write your reply to the new message.")
        prompt = build_messages(
            await self.personality_for(message.guild.id), bot_name, getattr(message.channel, "name", "dm"),
            history, message.author.display_name, message.clean_content, replying_to, memory_lines, task,
        )

        self._save_debug_prompt(prompt)
        self.budget.record(None if spontaneous else message.author.id)
        log.info("[AI] %s by %s in #%s", "spontaneous reply" if spontaneous else "reply requested",
                 message.author.id, getattr(message.channel, "name", "?"))
        try:
            if spontaneous:
                result = await self.router.chat(prompt, max_tokens=300)
            else:
                async with message.channel.typing():
                    result = await self.router.chat(prompt, max_tokens=300)
        except AllProvidersUnavailable:
            await self._usage(message, "none", "none", rate_limited=1)
            if not spontaneous:
                await self._offline_notice(message)
            return

        text = clean_reply(result.text, bot_name)
        await self._usage(message, result.provider, result.model, calls=1,
                          input_tokens=result.input_tokens, output_tokens=result.output_tokens)
        await self.send(message, text, spontaneous)

    def _save_debug_prompt(self, prompt) -> None:
        """Writes the exact prompt of the latest reply to data/last_prompt.txt, for checking what the AI was given."""
        try:
            path = self.db.path.parent / "last_prompt.txt"
            path.write_text("\n\n".join(f"===== {m.role.upper()} =====\n{m.content}" for m in prompt), encoding="utf-8")
        except OSError:
            pass

    async def send(self, message: discord.Message, text: str, spontaneous: bool) -> None:
        """Handles the AI's special answers ([skip], [react:X]) and sends normal text."""
        if not text or text.strip().lower().strip(".") in ("[skip]", "skip"):
            if not spontaneous:
                await _safe_react(message, "🤨")
            log.info("[AI] decided to stay quiet")
            return
        react = _REACT.fullmatch(text.strip())
        if react:
            await _safe_react(message, react.group(1).strip())
            return
        text = _REACT.sub("", text).strip()
        try:
            if spontaneous and random.random() < 0.5:
                await message.channel.send(text)  # sometimes just talk, like a person would
            else:
                await message.reply(text, mention_author=False)
        except discord.HTTPException as e:
            log.warning("Could not send reply: %s", e)

    async def _memories(self, message: discord.Message, history, participants: list[int]) -> dict[str, list[str]]:
        """A few relevant memories about the people talking, plus maybe one callback."""
        try:
            conversation = " ".join(text for _, text in history[-8:]) + " " + message.clean_content
            async with self.db.session() as s:
                found = await relevant_memories(
                    s, self.embedder, message.guild.id, participants, conversation,
                    callback_chance=self.personality.level("callbacks") / 10,
                    opted_out=lambda uid: self.privacy.user_opted_out(message.guild.id, uid),
                )
                await store.mark_referenced(s, [m.id for m in found["lore"]])
                public = {c.id for c in message.guild.text_channels
                          if c.permissions_for(message.guild.default_role).read_message_history
                          and not self.privacy.channel_excluded(c)}
                recalled = await recall_messages(s, message.guild.id, conversation, public,
                                                 message.channel.id, RECALL_MESSAGES)
                voice = await self.voice.samples(s, message.guild.id, participants, public,
                                                 lambda uid: self._name(message.guild, uid))
        except Exception:
            log.exception("Memory lookup failed; replying without memory")
            return {}
        people = []
        for m in found["people"]:
            names = [self._name(message.guild, uid) for uid in store.subject_ids(m)]
            people.append(f"{' & '.join(names)}: {m.text}")
        lore = [f"{m.title}: {m.text}" if m.title else m.text for m in found["lore"]]
        background = [f"{m.title}: {m.text}" if m.title else m.text for m in found["background"]]
        recall = [f"{self._name(message.guild, m.author_id)} ({m.created_at:%b %Y}): {m.content}" for m in recalled]
        log.info("[MEMORY] context: %d people memories, %d lore, %d background lore, %d recalled messages, "
                 "%d voice samples", len(people), len(lore), len(background), len(recall),
                 len(voice["people"]) + len(voice["hits"]))
        bible = self.bible.for_reply(message.guild.id, participants)
        log.info("[BIBLE] %s overview, %d character sheets", "with" if bible["bible_overview"] else "no",
                 len(bible["bible_people"]))
        return {"people": people, "lore": lore, "background": background, "recall": recall,
                "voice_people": voice["people"], "voice_hits": voice["hits"], **bible,
                "whos_who": self.nicknames.whos_who()}

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
