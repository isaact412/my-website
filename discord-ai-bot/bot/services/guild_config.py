"""Per-server settings (chattiness, roast level, personality overrides), cached in memory."""
import json
from dataclasses import dataclass, field

from bot.database.engine import Database
from bot.database.models import GuildSettings, utcnow


@dataclass
class GuildConfig:
    chattiness: int = 3
    roast_level: int = 5
    overrides: dict[str, int] = field(default_factory=dict)


class GuildConfigStore:
    def __init__(self, db: Database):
        self.db = db
        self._cache: dict[int, GuildConfig] = {}

    async def get(self, guild_id: int) -> GuildConfig:
        if guild_id not in self._cache:
            async with self.db.session() as s:
                row = await s.get(GuildSettings, guild_id)
            if row is None:
                self._cache[guild_id] = GuildConfig()
            else:
                try:
                    overrides = {k: int(v) for k, v in json.loads(row.personality_json or "{}").items()}
                except (ValueError, TypeError):
                    overrides = {}
                self._cache[guild_id] = GuildConfig(row.chattiness, row.roast_level, overrides)
        return self._cache[guild_id]

    async def update(self, guild_id: int, **changes) -> GuildConfig:
        cfg = await self.get(guild_id)
        for k, v in changes.items():
            setattr(cfg, k, v)
        async with self.db.session() as s:
            row = await s.get(GuildSettings, guild_id)
            if row is None:
                row = GuildSettings(guild_id=guild_id)
                s.add(row)
            row.chattiness, row.roast_level = cfg.chattiness, cfg.roast_level
            row.personality_json = json.dumps(cfg.overrides)
            row.updated_at = utcnow()
        return cfg
