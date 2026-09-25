"""Starts the bot. Run with:  python -m bot.main"""
import logging
import sys

import discord
from discord.ext import commands

from bot.config import ConfigError, Settings, load_settings
from bot.logging_setup import setup_logging

log = logging.getLogger("bot")

# Feature modules ("cogs") to load at startup. We add to this list each phase.
EXTENSIONS = [
    "bot.commands.general",
]


class DiscordAIBot(commands.Bot):
    def __init__(self, settings: Settings):
        intents = discord.Intents.default()
        intents.message_content = True  # read message text (enabled in the Developer Portal)
        intents.members = True          # nicknames, joins/leaves (enabled in the Developer Portal)

        super().__init__(
            command_prefix=commands.when_mentioned,  # no "!" commands; we use slash commands
            intents=intents,
            # Never let the bot ping @everyone, @here or roles, whatever it's told to say.
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True, replied_user=True),
        )
        self.settings = settings

    async def setup_hook(self) -> None:
        for ext in EXTENSIONS:
            await self.load_extension(ext)
            log.info("Loaded %s", ext)

        # Syncing to your test server makes slash commands appear instantly.
        if self.settings.dev_guild_id:
            guild = discord.Object(id=self.settings.dev_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d slash command(s) to test server", len(synced))
        else:
            synced = await self.tree.sync()
            log.info("Synced %d global slash command(s) (can take up to an hour to appear)", len(synced))

    async def on_ready(self) -> None:
        log.info("Bot connected as %s (id %s)", self.user, self.user.id)
        for guild in self.guilds:
            log.info("In server: %s (id %s)", guild.name, guild.id)


def main() -> None:
    try:
        settings = load_settings()
    except ConfigError as e:
        print(f"[CONFIG ERROR] {e}")
        sys.exit(1)

    setup_logging(settings.log_level, secrets=[settings.discord_token])
    bot = DiscordAIBot(settings)

    try:
        bot.run(settings.discord_token, log_handler=None)
    except discord.LoginFailure:
        log.error("Discord rejected the token. Reset it in the Developer Portal and paste the new one into .env.")
    except discord.PrivilegedIntentsRequired:
        log.error("Turn ON 'Server Members Intent' and 'Message Content Intent' in the Developer Portal → Bot, then Save.")


if __name__ == "__main__":
    main()
