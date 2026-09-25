"""Server admin commands. Require the Manage Server permission (or being the bot owner)."""
import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.database import repo

log = logging.getLogger("bot.commands")


def is_admin():
    """Checked on the bot's side, every time. Discord's menu hiding is not security."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id == interaction.client.settings.owner_user_id:
            return True
        perms = getattr(interaction.user, "guild_permissions", None)
        return bool(perms and perms.manage_guild)

    return app_commands.check(predicate)


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="usage", description="(admins) today's AI usage and cost")
    @app_commands.guild_only()
    @is_admin()
    async def usage(self, interaction: discord.Interaction) -> None:
        async with self.bot.db.session() as s:
            rows = await repo.usage_today(s, interaction.guild_id)

        replies = sum(r.calls for r in rows if r.kind == "reply")
        background = sum(r.calls for r in rows if r.kind == "background")
        free_calls = sum(r.calls - r.paid_calls for r in rows)
        paid_calls = sum(r.paid_calls for r in rows)
        cost = sum(r.est_cost_usd for r in rows)
        lines = [
            "**today**",
            f"ai replies: {replies}",
            f"background ai jobs: {background}",
            f"input tokens: {sum(r.input_tokens for r in rows):,}",
            f"output tokens: {sum(r.output_tokens for r in rows):,}",
            f"free api calls: {free_calls}",
            f"rate limited / unavailable: {sum(r.rate_limited for r in rows)}",
            f"paid api calls: {paid_calls}",
            f"estimated cost: ${cost:.2f}",
            "",
            f"mode: {'⚠️ PAID ALLOWED' if self.bot.settings.allow_paid_models else 'free only 🔒'}",
            f"providers: {', '.join(f'{p.name} ({p.model})' for p in self.bot.router.providers) or 'none'}",
            f"daily safety cap: {self.bot.budget.calls_today}/{self.bot.settings.ai_daily_call_limit} calls",
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @usage.error
    async def usage_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.CheckFailure):
            await interaction.response.send_message("admins only", ephemeral=True)
        else:
            log.exception("/usage failed", exc_info=error)
            if not interaction.response.is_done():
                await interaction.response.send_message("usage broke. check the logs.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Admin(bot))
