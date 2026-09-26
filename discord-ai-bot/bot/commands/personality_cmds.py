"""Admin commands for how the bot behaves: /chattiness, /roastlevel, /personality, /resetpersonality."""
import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.commands.admin import is_admin

log = logging.getLogger("bot.commands")

CHATTINESS_LABELS = {
    0: "mentions only", 1: "almost silent", 2: "rarely", 3: "occasional (default)", 4: "sometimes",
    5: "regular participant", 6: "talkative", 7: "very talkative", 8: "chaotic", 9: "unhinged",
    10: "please god make it stop",
}
SLIDERS = ["sarcasm", "chaos", "roasting", "helpfulness", "verbosity", "slang", "emoji", "weirdness",
           "raunchiness", "mirroring", "callbacks", "reactions"]


def _bar(n: int) -> str:
    return "█" * n + "░" * (10 - n)


class PersonalityCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="chattiness", description="(admins) how often the bot joins conversations on its own, 0-10")
    @app_commands.describe(level="0 = only when mentioned, 3 = default, 10 = absolute menace")
    @app_commands.guild_only()
    @is_admin()
    async def chattiness(self, interaction: discord.Interaction, level: app_commands.Range[int, 0, 10] | None = None) -> None:
        if level is None:
            cfg = await self.bot.guild_config.get(interaction.guild_id)
            await interaction.response.send_message(
                f"chattiness is **{cfg.chattiness}/10** ({CHATTINESS_LABELS[cfg.chattiness]})", ephemeral=True)
            return
        await self.bot.guild_config.update(interaction.guild_id, chattiness=level)
        log.info("chattiness → %d in guild %s by %s", level, interaction.guild_id, interaction.user.id)
        await interaction.response.send_message(f"chattiness set to **{level}/10**: {CHATTINESS_LABELS[level]}")

    @app_commands.command(name="roastlevel", description="(admins) how hard the bot roasts people, 0-10")
    @app_commands.guild_only()
    @is_admin()
    async def roastlevel(self, interaction: discord.Interaction, level: app_commands.Range[int, 0, 10]) -> None:
        cfg = await self.bot.guild_config.get(interaction.guild_id)
        overrides = {k: v for k, v in cfg.overrides.items() if k != "roasting"}
        await self.bot.guild_config.update(interaction.guild_id, roast_level=level, overrides=overrides)
        await interaction.response.send_message(f"roast level set to **{level}/10**" + (" 🔥" if level >= 8 else ""))

    @app_commands.command(name="personality", description="(admins) view the bot's personality sliders, or change one")
    @app_commands.describe(slider="which trait to change", value="0-10")
    @app_commands.choices(slider=[app_commands.Choice(name=s, value=s) for s in SLIDERS])
    @app_commands.guild_only()
    @is_admin()
    async def personality(self, interaction: discord.Interaction, slider: app_commands.Choice[str] | None = None,
                          value: app_commands.Range[int, 0, 10] | None = None) -> None:
        if slider and value is not None:
            cfg = await self.bot.guild_config.get(interaction.guild_id)
            if slider.value == "roasting":
                await self.bot.guild_config.update(interaction.guild_id, roast_level=value)
            else:
                await self.bot.guild_config.update(interaction.guild_id, overrides={**cfg.overrides, slider.value: value})
            log.info("personality %s → %d in guild %s", slider.value, value, interaction.guild_id)
        p = await self.bot.responder.personality_for(interaction.guild_id)
        cfg = await self.bot.guild_config.get(interaction.guild_id)
        lines = [f"`{s:<12}` {_bar(p.level(s))} {p.level(s)}" for s in SLIDERS]
        lines.append(f"`{'chattiness':<12}` {_bar(cfg.chattiness)} {cfg.chattiness}")
        header = f"updated **{slider.value}** to {value}.\n" if slider and value is not None else ""
        await interaction.response.send_message(header + "\n".join(lines), ephemeral=True)

    @app_commands.command(name="resetpersonality", description="(admins) put every slider back to the default")
    @app_commands.guild_only()
    @is_admin()
    async def resetpersonality(self, interaction: discord.Interaction) -> None:
        await self.bot.guild_config.update(interaction.guild_id, overrides={}, roast_level=5, chattiness=3)
        await interaction.response.send_message("personality reset to default. factory settings. lobotomized.")

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        msg = "admins only (you need Manage Server)" if isinstance(error, app_commands.CheckFailure) else "that broke. check the logs."
        if not isinstance(error, app_commands.CheckFailure):
            log.exception("Personality command failed", exc_info=error)
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PersonalityCommands(bot))
