"""Watches chat: saves messages locally, and decides when the bot should talk.

Reply rule for now: only when @mentioned or when someone replies to the bot.
(Spontaneous replies and /chattiness come in Phase 10.)
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
        if message.author.bot or message.guild is None:
            return  # ignore other bots (and ourselves) and DMs

        await self.bot.ingestor.store(message)  # checks exclusions and opt-outs itself

        if self.bot.privacy.channel_excluded(message.channel):
            return  # excluded channels: the bot stays completely out of it
        if self._is_addressed_to_me(message):
            try:
                await self.bot.responder.reply_to(message)
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
