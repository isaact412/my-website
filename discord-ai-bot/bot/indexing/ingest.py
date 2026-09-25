"""Saves messages locally (free, no AI) so they can be searched and analyzed later."""
import logging

import discord

from bot.database import repo
from bot.database.engine import Database
from bot.services.privacy import PrivacyState

log = logging.getLogger("bot.index")


class Ingestor:
    def __init__(self, db: Database, privacy: PrivacyState):
        self.db = db
        self.privacy = privacy
        self._known_names: dict[tuple[int, int], tuple] = {}  # skip name writes when nothing changed

    def should_store(self, message: discord.Message) -> bool:
        return (
            message.guild is not None
            and not message.author.bot
            and message.type in (discord.MessageType.default, discord.MessageType.reply)
            and not self.privacy.channel_excluded(message.channel)
            and not self.privacy.user_opted_out(message.guild.id, message.author.id)
        )

    async def store(self, message: discord.Message) -> None:
        if not self.should_store(message):
            return
        names = (message.author.name, message.author.global_name, getattr(message.author, "nick", None))
        key = (message.guild.id, message.author.id)
        try:
            async with self.db.session() as s:
                await repo.store_message(s, message)
                if self._known_names.get(key) != names:
                    await repo.upsert_user_names(s, message.author, message.guild.id)
            self._known_names[key] = names
        except Exception:
            log.exception("Could not store message %s", message.id)

    def forget_cached_names(self, guild_id: int, user_id: int | None = None) -> None:
        for key in list(self._known_names):
            if key[0] == guild_id and (user_id is None or key[1] == user_id):
                del self._known_names[key]
