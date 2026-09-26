# Discord AI Bot: Handoff

A Discord bot that acts like a regular member of a friend group's server. It chats when
@mentioned or replied to, and occasionally joins in on its own. It remembers members' running
jokes, habits and server lore, and it can read a server's full message history to learn that lore.
It runs at **$0**: free cloud AI for replies, local AI (Ollama) for background work, and local embeddings.

- Language: Python 3.12, discord.py 2.7
- Storage: SQLite (`data/bot.db`) via SQLAlchemy 2 (async, aiosqlite), migrations via Alembic
- AI: any OpenAI-compatible endpoint (Groq, OpenRouter, Ollama), with a free-only spending lock
- Embeddings: `fastembed` (BAAI/bge-small-en-v1.5), running on the CPU
- Tests: `pytest` (27 tests, no network needed)

---

## Running it

```bash
cd ~/discord-ai-bot
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # then fill in DISCORD_TOKEN, OWNER_USER_ID, GROQ_API_KEY
python -m bot.main       # runs database migrations automatically, then connects
```

Tests: `pip install pytest pytest-asyncio && python -m pytest -q tests`

The owner's Mac is updated with a generated one-paste installer, `setup_mac.sh`. Rebuild it after
changing any file with `tools/build_setup_script.sh`. It writes every tracked file into `~/discord-ai-bot`,
adds missing `.env` keys without touching existing values, installs requirements, and starts the bot.

### Discord application settings
- Privileged intents: **Message Content** ON, **Server Members** ON, Presence OFF
- OAuth2 scopes: `bot`, `applications.commands`
- Bot permissions: View Channels, Send Messages, Send Messages in Threads, Read Message History,
  Add Reactions, Embed Links, Use External Emojis (permissions integer `274878254144`). No Administrator.
- Slash commands sync instantly to `DEV_GUILD_ID`, or globally if it's unset (slow to appear).

### Environment (`.env`)
| Key | Purpose |
|---|---|
| `DISCORD_TOKEN`, `OWNER_USER_ID`, `DEV_GUILD_ID` | Discord login, owner-only commands, test server |
| `ALLOW_PAID_MODELS` | `false` by default. The spending lock refuses any model not verifiably free |
| `AI_PROVIDER_CHAIN` | Reply AI, tried in order (`groq`, `openrouter`, `ollama`) |
| `WORKER_PROVIDER_CHAIN` | Background memory/lore AI (usually `ollama`). Empty = use the reply chain |
| `GROQ_API_KEY`, `GROQ_MODEL=auto` | `auto` picks from Groq's live model list at startup |
| `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` | Only `:free` models or `openrouter/free`, price-checked |
| `OLLAMA_BASE_URL`, `OLLAMA_MODEL=auto` | `auto` = first downloaded local model. `:cloud` models are refused |
| `BACKGROUND_PARALLEL` | Simultaneous Ollama requests during history scans (default 2) |
| `HISTORY_USE_REPLY_AI` | Let scans also use the reply AI when Ollama exists (default false, protects reply quota) |
| `AI_MAX_CALLS_PER_MINUTE`, `AI_DAILY_CALL_LIMIT`, `AI_USER_COOLDOWN_SECONDS` | Reply limits |
| `BACKGROUND_DAILY_CALL_LIMIT`, `HISTORY_DAILY_CALL_LIMIT` | Background and scan limits |

---

## How a message flows

```
on_message (bot/listeners/messages.py)
 ├─ excluded channel / DM → ignore
 ├─ Ingestor.store → messages table + FTS5 index (skips bots, opted-out users)
 │     └─ MemoryExtractor.note → batches per channel; one AI call per ~40 msgs → memories
 ├─ @mention or reply to bot → Responder.reply_to
 └─ otherwise → ParticipationEngine.consider (free heuristics)
       ├─ maybe emoji reaction (rule-based, no AI)
       └─ maybe Responder.reply_to(spontaneous=True)  (AI may answer "[skip]")

Responder.reply_to (bot/services/responder.py)
 ├─ Budget check (per-user cooldown, per-minute, per-day)
 ├─ context: last 12 channel messages + replied-to message + participants
 ├─ relevant_memories: a few people-memories + maybe 1–2 relevant lore callbacks
 ├─ build_messages: system prompt (personality sliders + rules) + wrapped, untrusted chat data
 ├─ AIRouter.chat → first free provider available (FreeGuard checked on every call)
 └─ clean_reply → send ([skip] = stay quiet, [react:X] = emoji only)
```

Everything from Discord is treated as untrusted data: it's wrapped in `<chat_log>` / `<new_message>` tags
(fake tags are stripped), the AI never sees secrets, and `@everyone`/role pings are disabled at the client.

---

## File map

```
bot/
  main.py                 DiscordAIBot: wires everything, loads cogs (EXTENSIONS), startup/shutdown
  config.py               .env → Settings (validated); provider chains
  logging_setup.py        console + logs/bot.log, secrets redacted
  ai/
    providers/base.py     ChatMessage/ChatResult + error types (RateLimited, ProviderUnavailable, NotFreeError)
    providers/openai_compatible.py   one client for Groq/OpenRouter/Ollama; model auto-pick
    free_guard.py         spending lock, checked before every call
    router.py             tries free providers in order, cools down rate-limited ones
    budget.py             in-memory rate/daily limits
    prompts.py            system prompt, untrusted-data wrapping, reply cleanup
  character/personality.py   sliders (config/personality.yaml) → style rules; per-server overrides
  database/
    models.py             all tables (see below)
    engine.py             async engine, WAL mode, busy_timeout, session() context manager
    migrate.py            backs up bot.db, then runs Alembic to head on startup
    repo.py               message/user/privacy/usage queries (parameterized)
  indexing/ingest.py      saves live messages; notifies the memory extractor
  memory/
    extractor.py          batch → AI (JSON) → filter → reconcile (reinforce vs create) with embeddings
    store.py              memory queries, deletion/forget helpers, startup purge
    strength.py           tiers (temporary/useful/established/lore) + time decay
    retrieval.py          relevance scoring for replies; callback cooldown/chance
    embeddings.py         fastembed wrapper; falls back to keyword matching if unavailable
    sensitive.py          content filter applied before memories are saved
    scanner.py            /scanserver: parallel fetch → plan conversations → multi-lane digest
  services/
    responder.py          reply pipeline (above)
    decision.py           ParticipationEngine: when to join in / react; hard caps per channel
    reactions.py          regex → emoji
    guild_config.py       per-server chattiness / roast level / slider overrides (cached)
    privacy.py            in-memory excluded channels + opted-out users
  listeners/messages.py   on_message + edit/delete/channel-delete/nickname sync
  commands/               slash command cogs (see below)
  features/               search.py (/search), roast.py (/roastme)
  utils/confirm.py        yes/cancel button prompt
config/personality.yaml   default personality sliders + character description
migrations/versions/      0001 initial → 0005 scan_chunks (add new ones; never edit old ones)
tests/                    storage, AI layer (fake HTTP server), memory, scanner, decision
tools/build_setup_script.sh   regenerates setup_mac.sh
```

### Database tables
`guilds`, `users`, `user_names` (every username/display name/nickname, keyed by user ID),
`guild_settings`, `channel_settings`, `user_settings`, `usage_stats` (daily AI counters),
`messages` + `messages_fts` (FTS5, kept in sync by triggers), `memories` + `memory_sources`
(provenance: which messages a memory came from), `scan_jobs`, `scan_channels`, `scan_chunks`.

Schema changes: edit `models.py`, add `migrations/versions/000N_*.py` (use `batch_alter_table` for SQLite
column changes), then verify with `alembic check`.

---

## Slash commands

| Everyone | Admins (Manage Server) | Owner only |
|---|---|---|
| `/ping` `/search` `/lore` `/remember` `/whyremember` `/forget` (own memories) `/roastme` | `/usage` `/chattiness` `/roastlevel` `/personality` `/resetpersonality` | `/debug` `/memorynow` |
| `/privacy` `/whatdoyouknow` `/optout` `/optin` `/forgetme` | `/excludechannel` `/includechannel` `/clearmemory` `/scanserver` `/scanstatus` `/pausescan` `/resumescan` `/stopscan` | |

Permissions are checked on the bot's side (`is_admin()` in `commands/admin.py`, `is_owner()` in `commands/owner.py`).

---

## Memory model

- **Kinds:** `member` (about one person), `relationship` (two or more people), `lore` (server events, bits, quotes).
- **Reinforcement:** a new memory within 0.88 embedding similarity of an existing one reinforces it
  (`times_reinforced`, `distinct_days`, confidence +0.1) instead of creating a duplicate.
- **Tiers and decay** (`strength.py`): half-life of 3 days (temporary) / 30 days (useful) / 180 days (established) / ~10 years (lore).
- **Retrieval:** people currently talking get up to 6 memories. Lore is only included when relevance ≥ 0.55,
  it hasn't been referenced in 6 hours, and the `callbacks` slider's dice roll passes.
- **Scan:** conversations are split on 30-minute gaps (max 100 messages), scored locally (people, replies,
  laughs, words, recency), and learned highest-score first. Lanes: Ollama (parallel) and optionally the reply AI.

---

## Status

**Done:** Discord setup, `/ping`, database and migrations, free AI replies and spending lock, `/usage`,
privacy commands, message indexing and `/search`, layered memory, `/scanserver` (resumable), participation
engine (`/chattiness`, reactions, cooldowns), personality sliders, `/roastme`.

**Next (Phase 12, fun features):** `/profile`, `/recap hour|today|week`, `/quote` / `/randomquote` / `/addquote`,
`/whosaidthat` (game + scores), `/onthisday`, `/deepcut`, `/timeline`, `/stats`, music link memory
(`/musicstats`, `/randomsong`), bot moods, running opinions/bot beef, rotating status, `/yearbook`,
`/prophecy`, `/court`, `/awards`, `/bingo`, achievements. Build them as separate cogs in `bot/features/`,
use local SQL/FTS wherever possible, and only call the AI for the funny wording.

**Later:** 24/7 hosting (Oracle Cloud Always Free is the planned $0 option). Copy `data/bot.db` over.

**Conventions:** keep AI usage free-only through `AIRouter`/`FreeGuard`; never log secrets; all DB access through
`db.session()`; new tables via migrations; add tests alongside features; run `tools/build_setup_script.sh` after changes.
