"""Scanner tests with a fake Discord channel (no network)."""
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import discord
import pytest
import pytest_asyncio
from sqlalchemy import func, select

from bot.ai.budget import Budget
from bot.database import repo
from bot.database.engine import Database
from bot.database.migrate import upgrade_to_latest
from bot.database.models import Message, ScanChannel, ScanJob
from bot.memory import scanner as scanner_mod
from bot.memory.scanner import Scanner, estimate_channel

START = datetime(2024, 1, 1, tzinfo=timezone.utc)


def make_msgs(n, author=7, words=5):
    out = []
    for i in range(n):
        created = START + timedelta(minutes=i)
        out.append(SimpleNamespace(
            id=discord.utils.time_snowflake(created) + i, guild=SimpleNamespace(id=1), channel=SimpleNamespace(id=10),
            author=SimpleNamespace(id=author, name="alex", global_name=None, nick=None, bot=False),
            content=" ".join(["minecraft"] * words), reference=None, attachments=[], created_at=created,
            edited_at=None, type=discord.MessageType.default))
    return out


class FakeChannel:
    def __init__(self, msgs, fail_after=None):
        self.id, self.name, self.msgs, self.fail_after, self.reads = 10, "general", msgs, fail_after, 0

    def history(self, limit=None, after=None, oldest_first=False):
        msgs = sorted(self.msgs, key=lambda m: m.id, reverse=not oldest_first)
        if after is not None:
            msgs = [m for m in msgs if m.id > after.id]
        msgs = msgs[:limit] if limit else msgs

        async def gen():
            for m in msgs:
                self.reads += 1
                if self.fail_after and self.reads > self.fail_after:
                    raise RuntimeError("simulated crash")
                yield m
        return gen()


@pytest_asyncio.fixture
async def env(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(scanner_mod, "PAUSE_BETWEEN_PAGES", 0)
    upgrade_to_latest(tmp_path / "bot.db")
    db = Database(tmp_path / "bot.db")
    async with db.session() as s:
        await repo.upsert_guild(s, SimpleNamespace(id=1, name="test"))
    yield db
    await db.close()


def fake_bot(db, channel, analyze_results):
    calls = []

    async def analyze(guild_id, ids):
        calls.append(ids)
        return analyze_results.pop(0) if analyze_results else 1

    guild = SimpleNamespace(id=1, get_channel=lambda cid: channel if cid == 10 else None)
    bot = SimpleNamespace(
        get_guild=lambda gid: guild, get_channel=lambda cid: None,
        privacy=SimpleNamespace(channel_excluded=lambda c: False),
        ingestor=SimpleNamespace(should_store=lambda m: not m.author.bot),
        extractor=SimpleNamespace(analyze=analyze),
    )
    return bot, guild, calls


@pytest.mark.asyncio
async def test_scan_resumes_after_crash_and_digests(env, monkeypatch):
    db = env
    msgs = make_msgs(250) + make_msgs(60, words=1)  # last 60 are boring one-word messages
    for i, m in enumerate(msgs[250:]):
        m.id = msgs[249].id + 1000 + i
    channel = FakeChannel(msgs, fail_after=150)
    bot, guild, calls = fake_bot(db, channel, [])
    scanner = Scanner(bot, db, Budget(100, 100, 0))

    job_id = await scanner.create_job(guild, [(channel, 300)], 99, None)
    await scanner._tasks[1]  # crashes after 150 reads; first full page (100) was saved
    async with db.session() as s:
        sc = await s.get(ScanChannel, (job_id, 10))
        assert sc.fetched == 100 and not sc.fetch_done
        job = await s.get(ScanJob, job_id)
        job.created_at = datetime.now(timezone.utc)

    channel.fail_after = None
    await scanner.resume_after_restart()
    await scanner._tasks[1]
    async with db.session() as s:
        assert await s.scalar(select(func.count()).select_from(Message)) == 310
        sc = await s.get(ScanChannel, (job_id, 10))
        assert sc.fetch_done and sc.digest_done and sc.digested == 310
        assert (await s.get(ScanJob, job_id)).status == "done"
    # 310 messages → 6 chunks; the last two are mostly one-word messages, skipped without an AI call
    assert len(calls) == 4 and all(len(c) <= 60 for c in calls)
    assert "done" in await scanner.status_text(job_id)


@pytest.mark.asyncio
async def test_digest_retries_when_ai_unavailable(env, monkeypatch):
    db = env
    channel = FakeChannel(make_msgs(60))
    bot, guild, calls = fake_bot(db, channel, [None, 2])  # first attempt: no free AI available
    real_sleep = asyncio.sleep
    monkeypatch.setattr(scanner_mod.asyncio, "sleep", lambda s: real_sleep(0))
    scanner = Scanner(bot, db, Budget(100, 100, 0))
    job_id = await scanner.create_job(guild, [(channel, 60)], 99, None)
    async with db.session() as s:
        (await s.get(ScanJob, job_id)).created_at = datetime.now(timezone.utc)
    await scanner._tasks[1]
    assert len(calls) == 2 and calls[0] == calls[1]  # same chunk retried, nothing skipped


@pytest.mark.asyncio
async def test_estimate():
    assert await estimate_channel(FakeChannel(make_msgs(40))) == 40
    assert 900 <= await estimate_channel(FakeChannel(make_msgs(1000))) <= 1100
