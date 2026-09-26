"""Memory and lore commands: /remember, /lore, /forget, /whyremember."""
import logging
from datetime import date

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.database.models import Memory
from bot.memory import store
from bot.memory.embeddings import to_blob
from bot.memory.sensitive import is_sensitive
from bot.memory.strength import tier

log = logging.getLogger("bot.memory")


def _line(m: Memory, guild: discord.Guild, show_id: bool = True) -> str:
    who = ", ".join((guild.get_member(uid).display_name if guild.get_member(uid) else "someone")
                    for uid in store.subject_ids(m))
    head = f"**{m.title}**: " if m.title else (f"**{who}**: " if who else "")
    tail = f" `#{m.id} · {tier(m)}`" if show_id else ""
    return discord.utils.escape_mentions(f"• {head}{m.text}") + tail


class MemoryCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="remember", description="teach the bot a piece of server lore")
    @app_commands.describe(lore="e.g. 'the costco incident: ben tried to return a half-eaten rotisserie chicken'")
    @app_commands.guild_only()
    async def remember(self, interaction: discord.Interaction, lore: str) -> None:
        lore = lore.strip()[:300]
        if is_sensitive(lore):
            await interaction.response.send_message("not saving that one, it's personal stuff i don't keep.", ephemeral=True)
            return
        title, _, body = lore.partition(":")
        if not body.strip():
            title, body = "", lore
        vec = (await self.bot.embedder.embed([lore]) or [None])[0]
        async with self.bot.db.session() as s:
            m = await store.add_memory(
                s, guild_id=interaction.guild_id, kind="lore", subject_ids="", title=title.strip()[:120],
                text=body.strip(), keywords="", importance=3, confidence=0.9, times_reinforced=1, distinct_days=1,
                last_seen_day=date.today().isoformat(), pinned=True, active=True, embedding=to_blob(vec),
            )
            # Provenance: who taught it, when.
            await store.add_sources(s, m.id, [type("Src", (), dict(
                id=interaction.id, channel_id=interaction.channel_id, author_id=interaction.user.id,
                created_at=discord.utils.utcnow()))()])
        log.info("[MEMORY] /remember #%d by %s: %s", m.id, interaction.user.id, lore[:80])
        await interaction.response.send_message(f"noted. this is canon now. `#{m.id}`")

    @app_commands.command(name="lore", description="server lore: random, about someone, or search")
    @app_commands.describe(user="lore about this person", search="look for lore about something")
    @app_commands.guild_only()
    async def lore(self, interaction: discord.Interaction, user: discord.Member | None = None, search: str | None = None) -> None:
        async with self.bot.db.session() as s:
            if user:
                if self.bot.privacy.user_opted_out(interaction.guild_id, user.id):
                    await interaction.response.send_message(f"{user.display_name} opted out. no lore.", ephemeral=True)
                    return
                rows = (await store.about_user(s, interaction.guild_id, user.id))[:8]
                header = f"**lore: {discord.utils.escape_markdown(user.display_name)}**"
            elif search:
                rows = list(await s.scalars(select(Memory).where(
                    Memory.guild_id == interaction.guild_id, Memory.active.is_(True), Memory.kind == "lore",
                    store.search_filter(search[:50])).limit(8)))
                header = f"**lore about \"{discord.utils.escape_markdown(search[:50])}\"**"
            else:
                rows = await store.random_lore(s, interaction.guild_id, 3)
                header = "**random server lore**"
        if not rows:
            await interaction.response.send_message("no lore yet. either nothing's happened or i wasn't paying attention.", ephemeral=True)
            return
        await interaction.response.send_message(header + "\n" + "\n".join(_line(m, interaction.guild) for m in rows))

    @app_commands.command(name="forget", description="remove a wrong memory (admins, or the person it's about)")
    @app_commands.describe(memory_id="the #number shown next to the memory")
    @app_commands.guild_only()
    async def forget(self, interaction: discord.Interaction, memory_id: int) -> None:
        async with self.bot.db.session() as s:
            m = await store.get(s, interaction.guild_id, memory_id)
            if m is None:
                await interaction.response.send_message(f"no memory `#{memory_id}` here.", ephemeral=True)
                return
            perms = getattr(interaction.user, "guild_permissions", None)
            is_admin_user = interaction.user.id == self.bot.settings.owner_user_id or (perms and perms.manage_guild)
            is_about_them = interaction.user.id in store.subject_ids(m)
            if not (is_admin_user or is_about_them):
                await interaction.response.send_message("only admins or the person it's about can delete that.", ephemeral=True)
                return
            await store.delete_memory(s, m.id)
        log.info("[MEMORY] #%d forgotten by %s", memory_id, interaction.user.id)
        await interaction.response.send_message(f"forgot `#{memory_id}`. never happened.", ephemeral=True)

    @app_commands.command(name="whyremember", description="see which messages a memory came from")
    @app_commands.describe(memory_id="the #number shown next to the memory")
    @app_commands.guild_only()
    async def whyremember(self, interaction: discord.Interaction, memory_id: int) -> None:
        async with self.bot.db.session() as s:
            m = await store.get(s, interaction.guild_id, memory_id)
            srcs = await store.sources(s, memory_id) if m else []
        if m is None:
            await interaction.response.send_message(f"no memory `#{memory_id}` here.", ephemeral=True)
            return
        lines = [_line(m, interaction.guild),
                 f"seen {m.times_reinforced}x on {m.distinct_days} different day(s), confidence {m.confidence:.0%}"]
        shown = 0
        for src in srcs[:10]:
            channel = interaction.guild.get_channel_or_thread(src.channel_id)
            if channel is None or not channel.permissions_for(interaction.user).read_message_history:
                continue  # never reveal sources from channels this person can't read
            who = interaction.guild.get_member(src.author_id)
            lines.append(f"↳ {who.display_name if who else 'someone'} in {channel.mention} "
                         f"{discord.utils.format_dt(src.created_at, 'R')} "
                         f"[↗](https://discord.com/channels/{interaction.guild_id}/{src.channel_id}/{src.message_id})")
            shown += 1
        if not shown:
            lines.append("↳ no source messages you can see (added with /remember, or from channels you can't read)")
        await interaction.response.send_message("\n".join(lines), ephemeral=True, suppress_embeds=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MemoryCommands(bot))
