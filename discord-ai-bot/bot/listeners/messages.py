"""Watches chat and decides when the bot should talk.

Phase 7 rule: reply only when @mentioned or when someone replies to the bot.
(Spontaneous replies and /chattiness come in Phase 10.)
"""
import logging

import discord
from discord.ext import commands

log = logging.getLogger("bot.listeners")


class MessageListener(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return  # ignore other bots (and ourselves) and DMs

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
        if ref and isinstance(ref.resolved, discord.Message) and ref.resolved.author.id == me.id:
            return True
        return False


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MessageListener(bot))
