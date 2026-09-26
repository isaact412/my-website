"""Privacy commands anyone can use. Replies are private (only the user sees them)."""
import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.database import repo
from bot.memory import store
from bot.utils.confirm import ask

log = logging.getLogger("bot.privacy")


class Privacy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _analyzed_channels(self, guild: discord.Guild) -> list[discord.TextChannel]:
        me = guild.me
        return [
            c for c in guild.text_channels
            if c.permissions_for(me).view_channel and c.permissions_for(me).read_message_history
            and not self.bot.privacy.channel_excluded(c)
        ]

    @app_commands.command(name="privacy", description="what this bot stores and how to control it")
    @app_commands.guild_only()
    async def privacy(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        channels = self._analyzed_channels(guild)
        excluded = [f"<#{cid}>" for cid in self.bot.privacy.excluded_channels if guild.get_channel(cid)]
        provider_names = ", ".join(p.name for p in self.bot.router.providers) or "none"
        opted_out = self.bot.privacy.user_opted_out(guild.id, interaction.user.id)

        e = discord.Embed(title="privacy: what i actually do", color=discord.Color.dark_grey())
        e.add_field(name="what i read", inline=False, value=(
            "messages in channels i've been given access to. i can't see channels discord doesn't let me see, "
            "and i don't read DMs.\n"
            f"**channels i analyze:** {', '.join(c.mention for c in channels[:25]) or 'none'}"
            + (f"\n**excluded by admins:** {', '.join(excluded)}" if excluded else "")
        ))
        e.add_field(name="what i store", inline=False, value=(
            "• your messages in those channels (text, time, channel, who you replied to)\n"
            "• the names you go by here (username, display name, nickname), tied to your discord ID\n"
            "• memories: funny non-sensitive stuff like running jokes, quotes, games you talk about, "
            "server lore. each one links back to the messages it came from (`/whyremember`)\n"
            "i'm built **not** to store sensitive stuff (health, religion, politics, sexuality, etc).\n"
            "if you delete a message on discord, i delete my copy too."
        ))
        e.add_field(name="why", inline=False, value="so i can keep up with the conversation, search old stuff, and make callbacks to server lore.")
        e.add_field(name="ai", inline=False, value=(
            f"to write replies, recent chat is sent to a free AI service ({provider_names}). "
            "free AI services may keep or use what's sent to them under their own policies."
        ))
        e.add_field(name="your controls", inline=False, value=(
            "`/whatdoyouknow`: see what i have on you\n"
            "`/optout`: i stop storing your messages and building anything about you\n"
            "`/optin`: undo that\n"
            "`/forgetme`: delete everything i've stored about you here"
        ))
        e.set_footer(text=f"your status: {'opted out' if opted_out else 'included'}")
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="whatdoyouknow", description="see what the bot has stored about you")
    @app_commands.guild_only()
    async def whatdoyouknow(self, interaction: discord.Interaction) -> None:
        async with self.bot.db.session() as s:
            info = await repo.what_we_know(s, interaction.guild_id, interaction.user.id)
            memories = await store.about_user(s, interaction.guild_id, interaction.user.id)
        names = ", ".join(f"{v} ({k.replace('_', ' ')})" for k, v in info["names"]) or "none"
        first = discord.utils.format_dt(info["first_message"], "D") if info["first_message"] else "n/a"
        lines = [
            "**here's everything i have on you in this server:**",
            f"• stored messages: {info['messages']:,} (oldest: {first})",
            f"• names i've seen you use: {names}",
            f"• memories about you: {len(memories)}",
            *[f"  `#{m.id}` {discord.utils.escape_mentions(m.text)}" for m in memories[:10]],
            *(["  (…and more)"] if len(memories) > 10 else []),
            "wrong? `/forget <number>` · where'd that come from? `/whyremember <number>`",
            "",
            f"status: {'opted out' if self.bot.privacy.user_opted_out(interaction.guild_id, interaction.user.id) else 'included'}"
            " · `/forgetme` deletes all of it",
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(name="optout", description="stop the bot from storing your messages or building anything about you")
    @app_commands.guild_only()
    async def optout(self, interaction: discord.Interaction) -> None:
        async with self.bot.db.session() as s:
            await repo.set_opted_out(s, interaction.guild_id, interaction.user.id, True)
        self.bot.privacy.opted_out.add((interaction.guild_id, interaction.user.id))
        log.info("User %s opted out in guild %s", interaction.user.id, interaction.guild_id)
        await interaction.response.send_message(
            "done. i won't store your messages or build anything about you from now on. "
            "i'll still answer if you @ me directly. want your existing data gone too? use `/forgetme`.",
            ephemeral=True,
        )

    @app_commands.command(name="optin", description="let the bot include you again")
    @app_commands.guild_only()
    async def optin(self, interaction: discord.Interaction) -> None:
        async with self.bot.db.session() as s:
            await repo.set_opted_out(s, interaction.guild_id, interaction.user.id, False)
        self.bot.privacy.opted_out.discard((interaction.guild_id, interaction.user.id))
        log.info("User %s opted back in, guild %s", interaction.user.id, interaction.guild_id)
        await interaction.response.send_message("welcome back. i'll start keeping up with you again.", ephemeral=True)

    @app_commands.command(name="forgetme", description="delete everything the bot has stored about you in this server")
    @app_commands.guild_only()
    async def forgetme(self, interaction: discord.Interaction) -> None:
        if not await ask(interaction, "this deletes all your stored messages and names in this server. can't be undone. sure?",
                         "delete my data"):
            return
        async with self.bot.db.session() as s:
            deleted = await repo.forget_user(s, interaction.guild_id, interaction.user.id)
            forgotten = await store.forget_user_memories(s, interaction.guild_id, interaction.user.id)
        self.bot.ingestor.forget_cached_names(interaction.guild_id, interaction.user.id)
        log.info("Forgot user %s in guild %s (%d messages)", interaction.user.id, interaction.guild_id, deleted)
        opted = self.bot.privacy.user_opted_out(interaction.guild_id, interaction.user.id)
        await interaction.edit_original_response(content=(
            f"gone. deleted {deleted:,} messages, {forgotten} memories, and your saved names. "
            + ("you're still opted out, so i won't collect anything new." if opted
               else "i'll start fresh from your next message. use `/optout` if you don't want that.")
        ))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Privacy(bot))
