"""Tests for message storage, full-text search, and privacy deletion (real SQLite, fake Discord objects)."""
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio

from bot.database import repo
from bot.database.engine import Database
from bot.database.migrate import upgrade_to_latest


def fake_msg(mid, author, content, channel=10, guild=1):
    return SimpleNamespace(
        id=mid, guild=SimpleNamespace(id=guild), channel=SimpleNamespace(id=channel),
        author=SimpleNamespace(id=author, name=f"user{author}", global_name=None, nick=None),
        content=content, reference=None, attachments=[], created_at=datetime.now(timezone.utc), edited_at=None,
    )


@pytest_asyncio.fixture
async def db(tmp_path: Path):
    path = tmp_path / "bot.db"
    upgrade_to_latest(path)
    database = Database(path)
    async with database.session() as s:
        await repo.upsert_guild(s, SimpleNamespace(id=1, name="test"))
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_search_edit_delete(db):
    async with db.session() as s:
        await repo.store_message(s, fake_msg(100, 7, "we should make a minecraft server"))
        await repo.store_message(s, fake_msg(101, 8, "costco hot dogs are elite"))
        await repo.store_message(s, fake_msg(102, 7, 'minecraft AND "drop table" (again)'))
    async with db.session() as s:
        hits = await repo.search_messages(s, 1, "Minecraft", None)
        assert {m.id for m in hits} == {100, 102}
        assert [m.id for m in await repo.search_messages(s, 1, "minecraft", 8)] == []
        assert await repo.search_messages(s, 1, '") OR * NEAR(', None) == []  # hostile query is harmless
        await repo.update_message_content(s, 101, "sams club is better")
    async with db.session() as s:
        assert await repo.search_messages(s, 1, "costco", None) == []
        assert [m.id for m in await repo.search_messages(s, 1, "sams", None)] == [101]
        await repo.delete_messages(s, [101])
    async with db.session() as s:
        assert await repo.search_messages(s, 1, "sams", None) == []


@pytest.mark.asyncio
async def test_forget_user_and_clear(db):
    async with db.session() as s:
        for i, (author, text) in enumerate([(7, "hello there"), (7, "persona 5 is peak"), (8, "hello back")]):
            m = fake_msg(200 + i, author, text)
            await repo.store_message(s, m)
            await repo.upsert_user_names(s, m.author, 1)
    async with db.session() as s:
        info = await repo.what_we_know(s, 1, 7)
        assert info["messages"] == 2 and ("username", "user7") in [tuple(r) for r in info["names"]]
        assert await repo.forget_user(s, 1, 7) == 2
    async with db.session() as s:
        assert (await repo.what_we_know(s, 1, 7))["messages"] == 0
        assert await repo.search_messages(s, 1, "persona", None) == []
        assert (await repo.count_rows(s))["users"] == 1
        assert await repo.clear_guild_memory(s, 1) == 1
        assert (await repo.count_rows(s))["messages"] == 0


@pytest.mark.asyncio
async def test_upgrade_existing_0001_database(tmp_path: Path):
    """Simulates your Mac: a database at version 0001 gets backed up and upgraded."""
    from alembic import command
    from bot.database.migrate import _alembic_config, current_revision
    path = tmp_path / "bot.db"
    command.upgrade(_alembic_config(path), "0001")
    assert current_revision(path) == "0001"
    assert upgrade_to_latest(path) == "0003"
    assert list((tmp_path / "backups").glob("bot-*.db"))


def test_slash_commands_are_valid():
    """Loads every extension and checks Discord's limits on names/descriptions."""
    import asyncio
    from bot.config import Settings
    from bot.main import EXTENSIONS, DiscordAIBot

    async def load():
        settings = Settings("t", 1, None, "INFO", Path("x.db"), False, [], 20, 800, 8, 150)
        bot = DiscordAIBot(settings, Database(Path("/tmp/unused-test.db")), "0002")
        for ext in EXTENSIONS:
            await bot.load_extension(ext)
        return bot.tree.get_commands()

    cmds = asyncio.run(load())
    names = sorted(c.name for c in cmds)
    assert names == sorted(["ping", "debug", "memorynow", "remember", "lore", "forget", "whyremember", "usage", "excludechannel", "includechannel", "clearmemory",
                            "privacy", "whatdoyouknow", "optout", "optin", "forgetme", "search"])
    for c in cmds:
        assert len(c.description) <= 100 and c.name.islower()
