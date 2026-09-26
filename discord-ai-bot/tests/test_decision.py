"""Participation engine tests: when to talk, when to shut up (fake Discord objects, no network)."""
import time
from types import SimpleNamespace

import pytest

from bot.services import decision
from bot.services.decision import ParticipationEngine
from bot.services.guild_config import GuildConfig
from bot.services.reactions import pick_reaction
from bot.ai.prompts import clean_reply


class FakeCfgStore:
    def __init__(self, chattiness):
        self.cfg = GuildConfig(chattiness=chattiness)

    async def get(self, gid):
        return self.cfg


class FakeResponder:
    def __init__(self):
        self.calls = []

    async def reply_to(self, message, spontaneous=False, task=None):
        self.calls.append(message.content)


class FakeMsg:
    _next = 0

    def __init__(self, content, author=7):
        FakeMsg._next += 1
        self.id = FakeMsg._next
        self.content = content
        self.author = SimpleNamespace(id=author, bot=False)
        self.channel = SimpleNamespace(id=10, name="general")
        self.guild = SimpleNamespace(id=1, me=SimpleNamespace(display_name="tabchlolaursyd"))
        self.reactions = []

    async def add_reaction(self, e):
        self.reactions.append(e)


def make_engine(chattiness, monkeypatch, rolls=0.0):
    from bot.character.personality import Personality
    bot = SimpleNamespace(user=SimpleNamespace(id=999), guild_config=FakeCfgStore(chattiness),
                          personality=Personality({"reactions": 0}), responder=FakeResponder())
    engine = ParticipationEngine(bot)
    async def no_lore(guild_id, text):
        return False
    engine._hits_lore = no_lore
    monkeypatch.setattr(decision.random, "random", lambda: rolls)
    return engine, bot


@pytest.mark.asyncio
async def test_chattiness_zero_never_joins(monkeypatch):
    engine, bot = make_engine(0, monkeypatch, rolls=0.0)
    for text in ["tabchlolaursyd is so dumb", "what do yall think about the bot"]:
        m = FakeMsg(text); engine.observe(m); await engine.consider(m)
    assert bot.responder.calls == []


@pytest.mark.asyncio
async def test_hard_limits_hold_even_at_10(monkeypatch):
    engine, bot = make_engine(10, monkeypatch, rolls=0.0)  # dice always say yes
    for i in range(20):
        m = FakeMsg(f"the bot is talking again number {i}"); engine.observe(m); await engine.consider(m)
    assert len(bot.responder.calls) == 1  # MIN_GAP_SECONDS stops the rest
    engine._spoke[10].clear()
    for _ in range(25):
        engine._spoke[10].append(time.monotonic() - 3000)  # pretend it already spoke a lot this hour
    m = FakeMsg("bot bot bot"); engine.observe(m); await engine.consider(m)
    assert len(bot.responder.calls) == 1  # per-hour cap


@pytest.mark.asyncio
async def test_serious_messages_are_left_alone(monkeypatch):
    engine, bot = make_engine(10, monkeypatch, rolls=0.0)
    m = FakeMsg("my grandpa passed away this morning, bot"); engine.observe(m); await engine.consider(m)
    assert bot.responder.calls == [] and m.reactions == []


@pytest.mark.asyncio
async def test_score_rewards_bot_mentions_and_punishes_recent_talking(monkeypatch):
    engine, _ = make_engine(3, monkeypatch)
    about_bot = await engine.score(FakeMsg("honestly the bot has been funny today"))
    random_chat = await engine.score(FakeMsg("going to the store later"))
    assert about_bot > random_chat
    engine.note_bot_spoke(10)
    assert await engine.score(FakeMsg("honestly the bot has been funny today")) < about_bot


def test_reaction_rules_and_special_replies():
    assert pick_reaction("LMAO he actually did it") in ("💀", "😭")
    assert pick_reaction("i'll do it tomorrow trust me") in ("🫡", "🤨")
    assert pick_reaction("going to bed") is None
    assert clean_reply("[skip]", "bot") == "[skip]"


@pytest.mark.asyncio
async def test_responder_handles_skip_and_react(monkeypatch):
    from bot.services.responder import Responder
    sent = []

    class M(FakeMsg):
        async def reply(self, text, mention_author=False):
            sent.append(("reply", text))
    m = M("lol")
    m.channel.send = None
    r = Responder.__new__(Responder)
    await r.send(m, "[skip]", spontaneous=True)
    await r.send(m, "[react:💀]", spontaneous=True)
    await r.send(m, "bro what [react:💀]", spontaneous=False)
    assert m.reactions == ["💀"] and sent == [("reply", "bro what")]
