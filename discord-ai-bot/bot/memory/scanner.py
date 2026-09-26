"""/scanserver: reads a server's message history, then turns it into memories.

Phase 1, "fetch" (free, no AI): every chosen channel is read AT THE SAME TIME (each channel
has its own Discord rate limit), 100 messages per request, saved in one database write per page.
discord.py automatically waits when Discord says "slow down".

Phase 2, "plan" (free, no AI): history is split into conversations (a new one starts after a
30-minute gap). Each is scored locally: more people, replies, laughing, and recent = better.
Boring conversations are dropped here without any AI call.

Phase 3, "digest": the best conversations are turned into lore FIRST. Several AI "lanes" work in
parallel, e.g. Ollama on your Mac (no daily limit) plus Groq's free quota. A lane that's busy or
out of quota just waits; nothing is ever skipped or paid for.

Every step saves its progress, so a crash or restart resumes where it left off.
"""
import asyncio
import logging
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import discord
from sqlalchemy import func, select, update

from bot.ai.budget import Budget
from bot.ai.router import AIRouter
from bot.database import repo
from bot.database.engine import Database
from bot.database.models import Message, ScanChannel, ScanChunk, ScanJob, utcnow

log = logging.getLogger("bot.scan")

PAGE = 100
PARALLEL_CHANNELS = 6
CONVERSATION_GAP = 30 * 60   # seconds of silence that end a conversation
MAX_CHUNK = 100              # messages per AI call
MIN_WORDS_TO_DIGEST = 120    # conversations with less real text are skipped for free
PROGRESS_EVERY = 10          # seconds between progress message edits
RETRY_LANE_AFTER = 300       # seconds a lane waits when its AI is unavailable
_LAUGH = re.compile(r"lmao|lmfao|\blol\b|haha|💀|😭|😂|\bdead\b|crying", re.I)


@dataclass
class Lane:
    """One source of AI calls for history digestion."""
    name: str
    router: AIRouter
    budget: Budget
    workers: int = 1  # how many requests this lane sends at the same time


async def estimate_channel(channel: discord.TextChannel) -> int:
    """Rough message count: recent message rate × channel age. Discord has no cheap exact count."""
    try:
        first = [m async for m in channel.history(limit=1, oldest_first=True)]
        if not first:
            return 0
        recent = [m async for m in channel.history(limit=PAGE)]
    except (discord.Forbidden, discord.HTTPException):
        return 0
    if len(recent) < PAGE:
        return len(recent)
    recent_span = max(1.0, (recent[0].created_at - recent[-1].created_at).total_seconds())
    total_span = (recent[0].created_at - first[0].created_at).total_seconds()
    return max(PAGE, int(PAGE * total_span / recent_span))


def score_conversation(rows, now: datetime) -> float | None:
    """rows: (id, author_id, created_at, content, reply_to_id). None = not worth an AI call."""
    words = sum(len(r[3].split()) for r in rows)
    if words < MIN_WORDS_TO_DIGEST:
        return None
    authors = len({r[1] for r in rows})
    replies = sum(1 for r in rows if r[4])
    laughs = sum(1 for r in rows if _LAUGH.search(r[3]))
    last = rows[-1][2] if rows[-1][2].tzinfo else rows[-1][2].replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - last).total_seconds() / 86400)
    recency = 4 * math.pow(0.5, age_days / 365)
    return min(authors, 8) * 2 + replies * 0.5 + laughs + min(words, 2000) / 200 + recency


class Scanner:
    def __init__(self, bot, db: Database, lanes: list[Lane]):
        self.bot = bot
        self.db = db
        self.lanes = lanes
        self._tasks: dict[int, asyncio.Task] = {}   # guild_id -> running task
        self._notes: dict[int, dict[str, str]] = {}  # guild_id -> lane name -> what it's doing
        self._write_lock = asyncio.Lock()            # one database write at a time
        self._last_progress = 0.0

    # ---------- control ----------

    async def create_job(self, guild: discord.Guild, channels: list[tuple[discord.TextChannel, int]],
                         user_id: int, progress: discord.Message | None) -> int:
        async with self.db.session() as s:
            job = ScanJob(guild_id=guild.id, status="running", phase="fetch", started_by=user_id,
                          progress_channel_id=progress.channel.id if progress else None,
                          progress_message_id=progress.id if progress else None)
            s.add(job)
            await s.flush()
            for channel, estimate in channels:
                s.add(ScanChannel(job_id=job.id, channel_id=channel.id, name=channel.name[:100], estimate=estimate,
                                  fetched=0, fetch_cursor=0, fetch_done=False, digest_cursor=0, digested=0, digest_done=False))
            job_id = job.id
        log.info("[SCAN] job %d created for guild %s (%d channels) by %s", job_id, guild.id, len(channels), user_id)
        self._start(guild.id, job_id)
        return job_id

    def _start(self, guild_id: int, job_id: int) -> None:
        self._tasks[guild_id] = asyncio.create_task(self._run(job_id))

    def is_running(self, guild_id: int) -> bool:
        task = self._tasks.get(guild_id)
        return bool(task and not task.done())

    async def current_job(self, guild_id: int) -> ScanJob | None:
        async with self.db.session() as s:
            return await s.scalar(select(ScanJob).where(
                ScanJob.guild_id == guild_id, ScanJob.status.in_(["running", "paused"])).order_by(ScanJob.id.desc()))

    async def set_status(self, guild_id: int, status: str) -> ScanJob | None:
        """pause / stop / resume a guild's active job."""
        job = await self.current_job(guild_id)
        if job is None:
            return None
        task = self._tasks.pop(guild_id, None)
        if task:
            task.cancel()
        async with self.db.session() as s:
            row = await s.get(ScanJob, job.id)
            row.status, row.updated_at = status, utcnow()
        log.info("[SCAN] job %d → %s", job.id, status)
        if status == "running":
            self._start(guild_id, job.id)
        return job

    async def resume_after_restart(self) -> None:
        async with self.db.session() as s:
            jobs = list(await s.scalars(select(ScanJob).where(ScanJob.status == "running")))
        for job in jobs:
            if not self.is_running(job.guild_id):
                log.info("[SCAN] resuming job %d (%s phase) after restart", job.id, job.phase)
                self._start(job.guild_id, job.id)

    # ---------- status ----------

    async def status_text(self, job_id: int) -> str:
        async with self.db.session() as s:
            job = await s.get(ScanJob, job_id)
            chans = list(await s.scalars(select(ScanChannel).where(ScanChannel.job_id == job_id)))
            total_chunks = await s.scalar(select(func.count()).select_from(ScanChunk).where(ScanChunk.job_id == job_id))
            done_chunks = await s.scalar(select(func.count()).select_from(ScanChunk).where(
                ScanChunk.job_id == job_id, ScanChunk.done.is_(True)))
        fetched = sum(c.fetched for c in chans)
        estimate = sum(max(c.estimate, c.fetched) for c in chans)
        lines = [f"📚 **server history scan** (job #{job.id}, {job.status})"]
        if job.phase == "fetch":
            for c in [c for c in chans if not c.fetch_done][:PARALLEL_CHANNELS]:
                lines.append(f"reading **#{c.name}**... {c.fetched:,} / ~{max(c.estimate, c.fetched):,}")
        lines.append(f"channels read: {sum(c.fetch_done for c in chans)}/{len(chans)} · "
                     f"messages saved: {fetched:,}" + (f" / ~{estimate:,}" if job.phase == "fetch" else ""))
        if job.phase == "plan":
            lines.append("sorting history into conversations (free, no AI)...")
        if job.phase in ("digest", "done"):
            lines.append(f"learning lore (best conversations first): {done_chunks:,} / {total_chunks:,} conversations")
        for lane, note in self._notes.get(job.guild_id, {}).items():
            if job.status == "running":
                lines.append(f"_{lane}: {note}_")
        if job.status in ("running", "paused"):
            lines.append("`/scanstatus` · `/pausescan` · `/resumescan` · `/stopscan`")
        return "\n".join(lines)

    async def _update_progress(self, job: ScanJob, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_progress < PROGRESS_EVERY:
            return
        self._last_progress = now
        channel = self.bot.get_channel(job.progress_channel_id) if job.progress_channel_id else None
        if channel is None:
            return
        try:
            await channel.get_partial_message(job.progress_message_id).edit(content=await self.status_text(job.id))
        except discord.HTTPException:
            pass  # someone deleted the progress message; the scan carries on

    # ---------- the work ----------

    async def _run(self, job_id: int) -> None:
        try:
            async with self.db.session() as s:
                job = await s.get(ScanJob, job_id)
            guild = self.bot.get_guild(job.guild_id)
            if guild is None:
                log.warning("[SCAN] job %d: bot is no longer in that server; stopping", job_id)
                return await self._finish(job, "stopped")
            if job.phase == "fetch":
                await self._fetch_all(job, guild)
                await self._set_phase(job, "plan")
            if job.phase in ("plan", "digest"):  # "digest" without chunks = job from an older version
                await self._plan(job)
                await self._set_phase(job, "digest")
            await self._digest(job)
            await self._finish(job, "done")
        except asyncio.CancelledError:
            raise  # paused or stopped; progress is already saved
        except Exception:
            log.exception("[SCAN] job %d crashed; it will resume on next restart or /resumescan", job_id)

    async def _set_phase(self, job: ScanJob, phase: str) -> None:
        async with self.db.session() as s:
            (await s.get(ScanJob, job.id)).phase = phase
        job.phase = phase
        log.info("[SCAN] job %d → %s phase", job.id, phase)
        await self._update_progress(job, force=True)

    async def _finish(self, job: ScanJob, status: str) -> None:
        async with self.db.session() as s:
            row = await s.get(ScanJob, job.id)
            row.status, row.updated_at = status, utcnow()
            if status == "done":
                row.phase = "done"
        job.status = status
        self._notes.pop(job.guild_id, None)
        log.info("[SCAN] job %d %s", job.id, status)
        await self._update_progress(job, force=True)

    # --- phase 1: fetch ---

    async def _fetch_all(self, job: ScanJob, guild: discord.Guild) -> None:
        async with self.db.session() as s:
            chans = list(await s.scalars(select(ScanChannel).where(ScanChannel.job_id == job.id, ScanChannel.fetch_done.is_(False))))
        limit = asyncio.Semaphore(PARALLEL_CHANNELS)

        async def one(sc: ScanChannel) -> None:
            async with limit:
                channel = guild.get_channel(sc.channel_id)
                if channel is None or self.bot.privacy.channel_excluded(channel):
                    await self._mark(job.id, sc.channel_id, fetch_done=True)
                    return
                await self._fetch_channel(job, channel, sc)

        await asyncio.gather(*(one(sc) for sc in chans))

    async def _fetch_channel(self, job: ScanJob, channel: discord.TextChannel, sc: ScanChannel) -> None:
        cursor, fetched = sc.fetch_cursor, sc.fetched
        log.info("[SCAN] reading #%s from %s", channel.name, "the start" if not cursor else f"message {cursor}")
        batch: list[discord.Message] = []
        try:
            after = discord.Object(id=cursor) if cursor else None
            async for m in channel.history(limit=None, after=after, oldest_first=True):
                batch.append(m)
                if len(batch) >= PAGE:
                    fetched = await self._save_page(job, sc.channel_id, batch, fetched)
                    batch = []
                    await self._update_progress(job)
            if batch:
                fetched = await self._save_page(job, sc.channel_id, batch, fetched)
        except discord.Forbidden:
            log.warning("[SCAN] no permission to read #%s history; skipping it", channel.name)
        await self._mark(job.id, sc.channel_id, fetch_done=True)
        log.info("[SCAN] finished reading #%s (%d messages saved)", channel.name, fetched)

    async def _save_page(self, job: ScanJob, channel_id: int, batch: list[discord.Message], fetched: int) -> int:
        keep = [m for m in batch if self.bot.ingestor.should_store(m)]
        authors = {m.author.id: m.author for m in keep}
        async with self._write_lock, self.db.session() as s:
            await repo.store_messages_bulk(s, keep)
            for author in authors.values():
                await repo.upsert_user_names(s, author, job.guild_id)
            row = await s.get(ScanChannel, (job.id, channel_id))
            row.fetch_cursor, row.fetched = batch[-1].id, fetched + len(keep)
        return fetched + len(keep)

    # --- phase 2: plan ---

    async def _plan(self, job: ScanJob) -> None:
        async with self.db.session() as s:
            if await s.scalar(select(func.count()).select_from(ScanChunk).where(ScanChunk.job_id == job.id)):
                return  # already planned before a restart
            channel_ids = list(await s.scalars(select(ScanChannel.channel_id).where(ScanChannel.job_id == job.id)))
        cutoff = self._cutoff(job)
        now = datetime.now(timezone.utc)
        kept = skipped = 0
        for channel_id in channel_ids:
            conv, chunks = [], []

            def close():
                nonlocal kept, skipped
                if conv:
                    score = score_conversation(conv, now)
                    if score is None:
                        skipped += 1
                    else:
                        chunks.append(ScanChunk(job_id=job.id, channel_id=channel_id, start_id=conv[0][0],
                                                end_id=conv[-1][0], n_messages=len(conv), score=score, done=False))
                        kept += 1

            async with self.db.session() as s:
                result = await s.stream(
                    select(Message.id, Message.author_id, Message.created_at, Message.content, Message.reply_to_id)
                    .where(Message.channel_id == channel_id, Message.id < cutoff).order_by(Message.id))
                prev_time = None
                async for row in result:
                    t = row[2] if row[2].tzinfo else row[2].replace(tzinfo=timezone.utc)
                    if conv and ((t - prev_time).total_seconds() > CONVERSATION_GAP or len(conv) >= MAX_CHUNK):
                        close()
                        conv = []
                    conv.append(tuple(row))
                    prev_time = t
                close()
            async with self._write_lock, self.db.session() as s:
                s.add_all(chunks)
            await asyncio.sleep(0)  # let the bot answer chat between channels
        log.info("[SCAN] job %d planned: %d conversations to learn from, %d boring ones skipped", job.id, kept, skipped)

    # --- phase 3: digest ---

    async def _digest(self, job: ScanJob) -> None:
        async with self.db.session() as s:
            todo = list(await s.execute(select(ScanChunk.id, ScanChunk.channel_id, ScanChunk.start_id, ScanChunk.end_id)
                                        .where(ScanChunk.job_id == job.id, ScanChunk.done.is_(False))
                                        .order_by(ScanChunk.score.desc())))
        if not todo or not self.lanes:
            return
        queue: asyncio.Queue = asyncio.Queue()
        for row in todo:
            queue.put_nowait(tuple(row))
        await asyncio.gather(*(self._lane_worker(job, lane, queue, n)
                               for lane in self.lanes for n in range(lane.workers)))

    async def _lane_worker(self, job: ScanJob, lane: Lane, queue: asyncio.Queue, worker_no: int = 0) -> None:
        notes = self._notes.setdefault(job.guild_id, {})
        await asyncio.sleep(worker_no * 2)  # stagger start so workers don't collide on the first chunk
        cutoff = self._cutoff(job)
        while not queue.empty():
            while (reason := lane.budget.blocked_reason(None)):
                notes[lane.name] = "used today's free quota, continuing tomorrow" if "daily" in reason else "pacing"
                await asyncio.sleep(600 if "daily" in reason else 15)
            try:
                chunk_id, channel_id, start_id, end_id = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            async with self.db.session() as s:
                ids = list(await s.scalars(select(Message.id).where(
                    Message.channel_id == channel_id, Message.id >= start_id, Message.id <= end_id,
                    Message.id < cutoff).order_by(Message.id)))
            lane.budget.record(None)
            saved = await self.bot.extractor.analyze(job.guild_id, ids, router=lane.router) if ids else 0
            if saved is None:
                queue.put_nowait((chunk_id, channel_id, start_id, end_id))  # another lane (or this one later) retries it
                notes[lane.name] = "AI unavailable, retrying in 5 min"
                await self._update_progress(job, force=True)
                await asyncio.sleep(RETRY_LANE_AFTER)
                continue
            notes[lane.name] = "learning"
            async with self._write_lock, self.db.session() as s:
                await s.execute(update(ScanChunk).where(ScanChunk.id == chunk_id).values(done=True))
            await self._update_progress(job)
        notes.pop(lane.name, None)

    # --- helpers ---

    @staticmethod
    def _cutoff(job: ScanJob) -> int:
        """History = messages from before the scan started. Newer chat is learned live."""
        created = job.created_at if job.created_at.tzinfo else job.created_at.replace(tzinfo=timezone.utc)
        return discord.utils.time_snowflake(created)

    async def _mark(self, job_id: int, channel_id: int, **fields) -> None:
        async with self._write_lock, self.db.session() as s:
            row = await s.get(ScanChannel, (job_id, channel_id))
            for k, v in fields.items():
                setattr(row, k, v)
