"""In-memory copy of privacy settings, so every message can be checked instantly.

The database is the source of truth; this is loaded at startup and updated by the commands.
"""
from sqlalchemy import select

from bot.database.engine import Database
from bot.database.models import ChannelSetting, UserSetting


class PrivacyState:
    def __init__(self, db: Database):
        self.db = db
        self.excluded_channels: set[int] = set()
        self.opted_out: set[tuple[int, int]] = set()  # (guild_id, user_id)

    async def load(self) -> None:
        async with self.db.session() as s:
            self.excluded_channels = set(
                await s.scalars(select(ChannelSetting.channel_id).where(ChannelSetting.excluded.is_(True)))
            )
            rows = await s.execute(select(UserSetting.guild_id, UserSetting.user_id).where(UserSetting.opted_out.is_(True)))
            self.opted_out = {(g, u) for g, u in rows}

    def channel_excluded(self, channel) -> bool:
        """Threads inherit their parent channel's exclusion."""
        parent_id = getattr(channel, "parent_id", None)
        return channel.id in self.excluded_channels or (parent_id is not None and parent_id in self.excluded_channels)

    def user_opted_out(self, guild_id: int, user_id: int) -> bool:
        return (guild_id, user_id) in self.opted_out
