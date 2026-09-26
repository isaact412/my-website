"""/roastme: a roast built from harmless things the server actually knows about you."""
import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.ai.prompts import build_messages, clean_reply
from bot.memory import store

log = logging.getLogger("bot.commands")


class Roast(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="roastme", description="ask the bot to roast you using actual server lore")
    @app_commands.guild_only()
    async def roastme(self, interaction: discord.Interaction) -> None:
        if self.bot.budget.blocked_reason(interaction.user.id):
            await interaction.response.send_message("slow down, i'm still recovering from the last one", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        async with self.bot.db.session() as s:
            facts = [m.text for m in (await store.about_user(s, interaction.guild_id, interaction.user.id))[:8]]
        cfg = await self.bot.guild_config.get(interaction.guild_id)
        name = interaction.user.display_name
        known = "\n".join(f"- {f}" for f in facts) or "- (you barely know anything about them, roast them for being a mystery)"
        task = (f"{name} used /roastme and ASKED to be roasted. roast strength: {cfg.roast_level}/10. "
                f"build it from these real things you know about them:\n{known}\n"
                "be specific, not generic insults. no attacks on appearance, race, religion, sexuality, "
                "disability, or anything genuinely hurtful. 1-4 sentences.")
        personality = await self.bot.responder.personality_for(interaction.guild_id)
        prompt = build_messages(personality, interaction.guild.me.display_name, getattr(interaction.channel, "name", "?"),
                                [], name, "/roastme", None, None, task)
        self.bot.budget.record(interaction.user.id)
        try:
            result = await self.bot.router.chat(prompt, max_tokens=300)
            text = clean_reply(result.text, interaction.guild.me.display_name) or "i tried but you're unroastable. that's worse."
        except Exception:
            log.exception("/roastme failed")
            text = "my brain is buffering rn. consider yourself spared"
        await interaction.followup.send(text)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Roast(bot))
