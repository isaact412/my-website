"""Developer-only commands. Only OWNER_USER_ID from .env can use these."""
import logging
import platform
import time

import discord
from discord import app_commands
from discord.ext import commands

from bot.database import repo

log = logging.getLogger("bot.commands")


def is_owner():
    """Server-side check: hiding a command in Discord's menu is not security, this is."""

    async def predicate(interaction: discord.Interaction) -> bool:
        return interaction.user.id == interaction.client.settings.owner_user_id

    return app_commands.check(predicate)


class Owner(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="debug", description="(bot owner only) show bot health")
    @is_owner()
    async def debug(self, interaction: discord.Interaction) -> None:
        async with self.bot.db.session() as s:
            counts = await repo.count_rows(s)

        uptime_min = int((time.monotonic() - self.bot.started_at) // 60)
        lines = [
            "**debug**",
            f"latency: {round(self.bot.latency * 1000)}ms",
            f"uptime: {uptime_min} min",
            f"servers connected: {len(self.bot.guilds)}",
            f"database: `{self.bot.db.path}` (schema {self.bot.schema_version})",
            f"rows: {counts['guilds']} guilds, {counts['users']} users, {counts['messages']:,} messages",
            f"python {platform.python_version()} · discord.py {discord.__version__}",
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(name="memorynow", description="(bot owner only) analyze this channel's recent messages for memories now")
    @is_owner()
    async def memorynow(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        saved = await self.bot.extractor.run_channel(interaction.channel_id, interaction.guild_id, force=True)
        embeddings = "on" if self.bot.embedder.available else "off (keyword fallback)"
        await interaction.followup.send(
            f"done: {saved} memories saved/reinforced. embeddings: {embeddings}. check `/whatdoyouknow` or `/lore`.",
            ephemeral=True,
        )

    @memorynow.error
    @debug.error
    async def debug_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.CheckFailure):
            await interaction.response.send_message("nice try", ephemeral=True)
            log.info("Blocked /debug from non-owner %s", interaction.user.id)
        else:
            log.exception("/debug failed", exc_info=error)
            if not interaction.response.is_done():
                await interaction.response.send_message("debug broke. check the logs.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Owner(bot))
