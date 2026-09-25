"""/search: exact-word search over stored messages. 100% local, no AI."""
import discord
from discord import app_commands
from discord.ext import commands

from bot.database import repo

SHOW = 5


class Search(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="search", description="search old messages in this server")
    @app_commands.describe(words="what to look for", user="only messages from this person")
    @app_commands.guild_only()
    async def search(self, interaction: discord.Interaction, words: str, user: discord.Member | None = None) -> None:
        async with self.bot.db.session() as s:
            results = await repo.search_messages(s, interaction.guild_id, words, user.id if user else None)

        # Only show messages from channels the person searching is allowed to read.
        visible = []
        for m in results:
            channel = interaction.guild.get_channel_or_thread(m.channel_id)
            if channel and channel.permissions_for(interaction.user).read_message_history:
                visible.append((m, channel))
            if len(visible) == SHOW:
                break

        if not visible:
            await interaction.response.send_message(f"found nothing for `{words[:50]}`", ephemeral=True)
            return

        lines = []
        for m, channel in visible:
            author = interaction.guild.get_member(m.author_id)
            name = author.display_name if author else "someone who left"
            text = discord.utils.escape_mentions(discord.utils.escape_markdown(m.content))[:180]
            link = f"https://discord.com/channels/{m.guild_id}/{m.channel_id}/{m.id}"
            lines.append(f"**{name}** in {channel.mention} {discord.utils.format_dt(m.created_at, 'R')}: {text} [↗]({link})")
        await interaction.response.send_message("\n".join(lines), ephemeral=True, suppress_embeds=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Search(bot))
