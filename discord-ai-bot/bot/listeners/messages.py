"""Watches chat: saves messages locally, and decides when the bot should talk.

Always replies when @mentioned or replied to. Otherwise bot/services/decision.py decides
(usually: stay quiet, sometimes react, occasionally join in, per /chattiness).
"""
import logging

import discord
from discord.ext import commands

from bot.database import repo

log = logging.getLogger("bot.listeners")


class MessageListener(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or self.bot.privacy.channel_excluded(message.channel):
            return  # no DMs; excluded channels: the bot stays completely out of it
        if message.author.id == self.bot.user.id:
            self.bot.participation.observe(message)  # remember that we spoke, for pacing
            return
        if message.author.bot:
            return  # ignore other bots

        await self.bot.ingestor.store(message)  # checks opt-outs itself
        self.bot.participation.observe(message)
        try:
            if self._is_addressed_to_me(message):
                await self.bot.responder.reply_to(message)
            else:
                await self.bot.participation.consider(message)
        except Exception:
            # One bad message must never crash the bot.
            log.exception("Reply pipeline failed for message %s", message.id)

    def _is_addressed_to_me(self, message: discord.Message) -> bool:
        me = self.bot.user
        if me in message.mentions:
            return True
        ref = message.reference
        return bool(ref and isinstance(ref.resolved, discord.Message) and ref.resolved.author.id == me.id)

    # Keep our copy in sync with Discord. "raw" events fire even for old, uncached messages.

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent) -> None:
        content = payload.data.get("content")
        if content is None:
            return  # embed-only update, not a real edit
        await self._db(repo.update_message_content, payload.message_id, content)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        await self._db(repo.delete_messages, [payload.message_id])

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent) -> None:
        await self._db(repo.delete_messages, list(payload.message_ids))

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        await self._db(repo.delete_channel_messages, channel.id)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.nick != after.nick and not after.bot and not self.bot.privacy.user_opted_out(after.guild.id, after.id):
            await self._db(repo.upsert_user_names, after, after.guild.id)

    async def _db(self, fn, *args) -> None:
        try:
            async with self.bot.db.session() as s:
                await fn(s, *args)
        except Exception:
            log.exception("Database update failed (%s)", fn.__name__)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MessageListener(bot))
