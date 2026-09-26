"""Server admin commands. Require the Manage Server permission (or being the bot owner)."""
import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.database import repo
from bot.memory import store
from bot.utils.confirm import ask

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

    @app_commands.command(name="excludechannel", description="(admins) bot stops reading and replying in a channel, and deletes what it stored from it")
    @app_commands.guild_only()
    @is_admin()
    async def excludechannel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        async with self.bot.db.session() as s:
            await repo.set_channel_excluded(s, interaction.guild_id, channel.id, True)
            deleted = await repo.delete_channel_messages(s, channel.id)
            await store.forget_channel_memories(s, interaction.guild_id, channel.id)
        self.bot.privacy.excluded_channels.add(channel.id)
        log.info("Excluded channel %s in guild %s (%d stored messages deleted)", channel.id, interaction.guild_id, deleted)
        await interaction.response.send_message(
            f"{channel.mention} is now excluded. i deleted {deleted:,} stored messages from it and won't read or reply there.",
            ephemeral=True,
        )

    @app_commands.command(name="includechannel", description="(admins) let the bot read a previously excluded channel again")
    @app_commands.guild_only()
    @is_admin()
    async def includechannel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        async with self.bot.db.session() as s:
            await repo.set_channel_excluded(s, interaction.guild_id, channel.id, False)
        self.bot.privacy.excluded_channels.discard(channel.id)
        log.info("Included channel %s in guild %s", channel.id, interaction.guild_id)
        await interaction.response.send_message(f"{channel.mention} is included again (new messages only).", ephemeral=True)

    @app_commands.command(name="clearmemory", description="(admins) delete everything the bot stored about this server")
    @app_commands.guild_only()
    @is_admin()
    async def clearmemory(self, interaction: discord.Interaction) -> None:
        if not await ask(interaction, "this deletes ALL stored messages, memories, lore and nicknames for this server. settings and "
                                      "opt-outs are kept. can't be undone. sure?", "delete server memory"):
            return
        async with self.bot.db.session() as s:
            deleted = await repo.clear_guild_memory(s, interaction.guild_id)
            memories = await store.clear_guild(s, interaction.guild_id)
        self.bot.ingestor.forget_cached_names(interaction.guild_id)
        log.info("Cleared memory for guild %s (%d messages) by %s", interaction.guild_id, deleted, interaction.user.id)
        await interaction.edit_original_response(content=f"done. deleted {deleted:,} stored messages and {memories} memories. fresh start.")

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.CheckFailure):
            msg = "admins only (you need Manage Server)"
        else:
            log.exception("Admin command failed", exc_info=error)
            msg = "that broke. check the logs."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Admin(bot))
