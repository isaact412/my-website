"""Admin commands for scanning server history: /scanserver, /scanstatus, /pausescan, /resumescan, /stopscan."""
import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.commands.admin import is_admin
from bot.memory.scanner import MAX_CHUNK, PAGE, PARALLEL_CHANNELS, estimate_channel

log = logging.getLogger("bot.scan")


class ScanSetup(discord.ui.View):
    """Channel picker + start/cancel buttons. Only the admin who ran /scanserver can use it."""

    def __init__(self, cog: "ScanCommands", user_id: int, channels: list[tuple[discord.TextChannel, int]]):
        super().__init__(timeout=300)
        self.cog, self.user_id = cog, user_id
        self.estimates = {c.id: (c, est) for c, est in channels}
        self.selected = set(self.estimates)
        self.picker.options = [
            discord.SelectOption(label=f"#{c.name}"[:100], value=str(c.id), description=f"~{est:,} messages", default=True)
            for c, est in channels[:25]
        ]
        self.picker.max_values = len(self.picker.options)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    @discord.ui.select(placeholder="channels to scan", min_values=1)
    async def picker(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        self.selected = {int(v) for v in select.values}
        for opt in select.options:
            opt.default = opt.value in select.values
        await interaction.response.edit_message(content=self.cog.plan_text(self), view=self)

    @discord.ui.button(label="start scan", style=discord.ButtonStyle.success)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content="starting. progress will be posted in this channel.", view=None)
        progress = await interaction.channel.send("📚 starting server history scan...")
        chosen = [self.estimates[cid] for cid in self.selected]
        await self.cog.bot.scanner.create_job(interaction.guild, chosen, interaction.user.id, progress)

    @discord.ui.button(label="cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content="cancelled. nothing was scanned.", view=None)


class ScanCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def plan_text(self, view: ScanSetup) -> str:
        chosen = [view.estimates[cid] for cid in view.selected]
        total = sum(est for _, est in chosen)
        biggest = max((est for _, est in chosen), default=0)
        # Channels are read in parallel, so the biggest channel sets the pace (~0.4s per 100 messages).
        minutes = max(1, round(max(biggest, total / PARALLEL_CHANNELS) / PAGE * 0.4 / 60))
        ai_calls = round(total / MAX_CHUNK * 0.5)  # boring conversations are skipped for free
        per_day = self.bot.settings.history_daily_call_limit
        local = bool(self.bot.worker_router)
        days = max(1, -(-ai_calls // per_day)) if ai_calls else 0
        lines = [
            "**here's what `/scanserver` will do:**",
            f"1. read **~{total:,} messages** from {len(chosen)} channel(s) and save them on the bot's computer "
            f"(free, about **{minutes} min**). bots, excluded channels and opted-out people are skipped.",
            f"2. turn that history into memories and lore, **best conversations first** (~{ai_calls:,} AI calls). "
            + ("uses your computer's local AI with no daily limit, plus the cloud's free quota. costs $0."
               if local else f"free cloud AI only: up to {per_day}/day, so about **{days} day(s)**. costs $0."),
            "it can be paused, resumed or stopped anytime, and picks up where it left off after a restart.",
            "",
            "**channels** (estimates are rough):",
            *[f"• #{c.name}: ~{est:,}" for c, est in chosen[:25]],
        ]
        if len(view.estimates) > 25:
            lines.append(f"(only the first 25 channels can be picked here; {len(view.estimates) - 25} more can be scanned later)")
        return "\n".join(lines)

    @app_commands.command(name="scanserver", description="(admins) read this server's message history so the bot knows the lore")
    @app_commands.guild_only()
    @is_admin()
    async def scanserver(self, interaction: discord.Interaction) -> None:
        if await self.bot.scanner.current_job(interaction.guild_id):
            await interaction.response.send_message("a scan is already going. `/scanstatus` to check on it.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        me = interaction.guild.me
        readable = [c for c in interaction.guild.text_channels
                    if c.permissions_for(me).view_channel and c.permissions_for(me).read_message_history
                    and not self.bot.privacy.channel_excluded(c)]
        if not readable:
            await interaction.followup.send("i can't read any channels here. check my permissions.", ephemeral=True)
            return
        channels = [(c, await estimate_channel(c)) for c in readable[:25]]
        channels.sort(key=lambda x: x[1], reverse=True)
        view = ScanSetup(self, interaction.user.id, channels)
        await interaction.followup.send(self.plan_text(view), view=view, ephemeral=True)

    @app_commands.command(name="scanstatus", description="(admins) progress of the history scan")
    @app_commands.guild_only()
    @is_admin()
    async def scanstatus(self, interaction: discord.Interaction) -> None:
        job = await self.bot.scanner.current_job(interaction.guild_id)
        text = await self.bot.scanner.status_text(job.id) if job else "no scan running. `/scanserver` to start one."
        await interaction.response.send_message(text, ephemeral=True)

    @app_commands.command(name="pausescan", description="(admins) pause the history scan")
    @app_commands.guild_only()
    @is_admin()
    async def pausescan(self, interaction: discord.Interaction) -> None:
        job = await self.bot.scanner.set_status(interaction.guild_id, "paused")
        await interaction.response.send_message("paused. `/resumescan` to continue." if job else "no scan running.", ephemeral=True)

    @app_commands.command(name="resumescan", description="(admins) continue a paused history scan")
    @app_commands.guild_only()
    @is_admin()
    async def resumescan(self, interaction: discord.Interaction) -> None:
        job = await self.bot.scanner.set_status(interaction.guild_id, "running")
        await interaction.response.send_message("resumed." if job else "nothing to resume.", ephemeral=True)

    @app_commands.command(name="stopscan", description="(admins) stop the history scan (what's saved so far is kept)")
    @app_commands.guild_only()
    @is_admin()
    async def stopscan(self, interaction: discord.Interaction) -> None:
        job = await self.bot.scanner.set_status(interaction.guild_id, "stopped")
        await interaction.response.send_message("stopped. everything read so far is kept." if job else "no scan running.", ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        msg = "admins only (you need Manage Server)" if isinstance(error, app_commands.CheckFailure) else "that broke. check the logs."
        if not isinstance(error, app_commands.CheckFailure):
            log.exception("Scan command failed", exc_info=error)
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ScanCommands(bot))
