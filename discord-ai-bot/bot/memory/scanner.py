"""/scanserver: reads a server's message history, then slowly turns it into memories.

Phase 1, "fetch" (free, no AI): every message in the chosen channels is saved locally,
100 at a time, oldest first. Discord's rate limits are respected automatically by
discord.py, and we pause between pages to be polite.

Phase 2, "digest" (free AI, rate-limited): stored history is read in chunks of 60 and
turned into memories/lore. Boring chunks are skipped without any AI call. This phase
runs within HISTORY_DAILY_CALL_LIMIT and simply waits for the next day's free quota.

Both phases save a cursor after every step, so a crash or restart resumes where it left off.
"""
import asyncio
import logging
import time
from datetime import timezone

import discord
from sqlalchemy import select

from bot.ai.budget import Budget
from bot.database import repo
from bot.database.engine import Database
from bot.database.models import Message, ScanChannel, ScanJob, utcnow

log = logging.getLogger("bot.scan")

PAGE = 100
PAUSE_BETWEEN_PAGES = 0.6   # seconds
DIGEST_CHUNK = 60
MIN_WORDS_TO_DIGEST = 120   # chunks with less real text than this are skipped for free
PROGRESS_EVERY = 10         # seconds between progress message edits


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


class Scanner:
    def __init__(self, bot, db: Database, budget: Budget):
        self.bot = bot
        self.db = db
        self.budget = budget
        self._tasks: dict[int, asyncio.Task] = {}   # guild_id -> running task
        self._phase_note: dict[int, str] = {}

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
                log.info("[SCAN] resuming job %d after restart", job.id)
                self._start(job.guild_id, job.id)

    # ---------- status ----------

    async def status_text(self, job_id: int) -> str:
        async with self.db.session() as s:
            job = await s.get(ScanJob, job_id)
            chans = list(await s.scalars(select(ScanChannel).where(ScanChannel.job_id == job_id)))
        fetched = sum(c.fetched for c in chans)
        estimate = sum(max(c.estimate, c.fetched) for c in chans)
        digested = sum(c.digested for c in chans)
        lines = [f"📚 **server history scan** (job #{job.id}, {job.status})"]
        current = next((c for c in chans if not c.fetch_done), None)
        if current:
            lines.append(f"reading **#{current.name}**... {current.fetched:,} / ~{max(current.estimate, current.fetched):,}")
        lines.append(f"channels read: {sum(c.fetch_done for c in chans)}/{len(chans)} · "
                     f"messages saved: {fetched:,} / ~{estimate:,}")
        if job.phase in ("digest", "done"):
            lines.append(f"learning lore: {digested:,} / {fetched:,} messages analyzed")
        note = self._phase_note.get(job.guild_id)
        if note and job.status == "running":
            lines.append(f"_{note}_")
        if job.status in ("running", "paused"):
            lines.append("`/scanstatus` · `/pausescan` · `/resumescan` · `/stopscan`")
        return "\n".join(lines)

    async def _update_progress(self, job: ScanJob, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - getattr(self, "_last_progress", 0) < PROGRESS_EVERY:
            return
        self._last_progress = now
        if not job.progress_channel_id:
            return
        channel = self.bot.get_channel(job.progress_channel_id)
        if channel is None:
            return
        try:
            msg = channel.get_partial_message(job.progress_message_id)
            await msg.edit(content=await self.status_text(job.id))
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
                async with self.db.session() as s:
                    (await s.get(ScanJob, job_id)).phase = "digest"
                job.phase = "digest"
                await self._update_progress(job, force=True)
            await self._digest_all(job, guild)
            await self._finish(job, "done")
        except asyncio.CancelledError:
            raise  # paused or stopped; progress is already saved
        except Exception:
            log.exception("[SCAN] job %d crashed; it will resume on next restart or /resumescan", job_id)

    async def _finish(self, job: ScanJob, status: str) -> None:
        async with self.db.session() as s:
            row = await s.get(ScanJob, job.id)
            row.status, row.phase, row.updated_at = status, "done" if status == "done" else row.phase, utcnow()
        job.status = status
        self._phase_note.pop(job.guild_id, None)
        log.info("[SCAN] job %d %s", job.id, status)
        await self._update_progress(job, force=True)

    async def _fetch_all(self, job: ScanJob, guild: discord.Guild) -> None:
        async with self.db.session() as s:
            chans = list(await s.scalars(select(ScanChannel).where(ScanChannel.job_id == job.id, ScanChannel.fetch_done.is_(False))))
        for sc in chans:
            channel = guild.get_channel(sc.channel_id)
            if channel is None or self.bot.privacy.channel_excluded(channel):
                await self._mark(job.id, sc.channel_id, fetch_done=True)
                continue
            await self._fetch_channel(job, channel, sc)

    async def _fetch_channel(self, job: ScanJob, channel: discord.TextChannel, sc: ScanChannel) -> None:
        cursor, fetched = sc.fetch_cursor, sc.fetched
        log.info("[SCAN] reading #%s from %s", channel.name, "the start" if not cursor else f"message {cursor}")
        batch: list[discord.Message] = []
        try:
            after = discord.Object(id=cursor) if cursor else None
            async for m in channel.history(limit=None, after=after, oldest_first=True):
                batch.append(m)
                if len(batch) >= PAGE:
                    cursor, fetched = await self._save_page(job, sc.channel_id, batch, fetched)
                    batch = []
                    await self._update_progress(job)
                    await asyncio.sleep(PAUSE_BETWEEN_PAGES)
            if batch:
                cursor, fetched = await self._save_page(job, sc.channel_id, batch, fetched)
        except discord.Forbidden:
            log.warning("[SCAN] no permission to read #%s history; skipping it", channel.name)
        await self._mark(job.id, sc.channel_id, fetch_done=True)
        log.info("[SCAN] finished reading #%s (%d messages seen)", channel.name, fetched)

    async def _save_page(self, job: ScanJob, channel_id: int, batch: list[discord.Message], fetched: int):
        keep = [m for m in batch if self.bot.ingestor.should_store(m)]
        async with self.db.session() as s:
            authors = {}
            for m in keep:
                await repo.store_message(s, m)
                authors[m.author.id] = m.author
            for author in authors.values():
                await repo.upsert_user_names(s, author, job.guild_id)
            row = await s.get(ScanChannel, (job.id, channel_id))
            row.fetch_cursor, row.fetched = batch[-1].id, fetched + len(keep)
        return batch[-1].id, fetched + len(keep)

    async def _digest_all(self, job: ScanJob, guild: discord.Guild) -> None:
        # Only digest history from before the scan started; newer chat is handled live.
        cutoff = discord.utils.time_snowflake(job.created_at.replace(tzinfo=job.created_at.tzinfo or timezone.utc))
        async with self.db.session() as s:
            chans = list(await s.scalars(select(ScanChannel).where(ScanChannel.job_id == job.id, ScanChannel.digest_done.is_(False))))
        for sc in chans:
            cursor, digested = sc.digest_cursor, sc.digested
            while True:
                async with self.db.session() as s:
                    rows = list(await s.execute(
                        select(Message.id, Message.content).where(
                            Message.channel_id == sc.channel_id, Message.id > cursor, Message.id < cutoff)
                        .order_by(Message.id).limit(DIGEST_CHUNK)))
                if not rows:
                    break
                ids = [r[0] for r in rows]
                words = sum(len(r[1].split()) for r in rows)
                if words >= MIN_WORDS_TO_DIGEST:
                    await self._wait_for_budget(job)
                    self.budget.record(None)
                    saved = await self.bot.extractor.analyze(job.guild_id, ids)
                    if saved is None:  # free AI unavailable right now: wait, then retry this same chunk
                        self._phase_note[job.guild_id] = "free AI busy, retrying in 5 minutes"
                        await self._update_progress(job, force=True)
                        await asyncio.sleep(300)
                        continue
                self._phase_note.pop(job.guild_id, None)
                cursor, digested = ids[-1], digested + len(ids)
                await self._mark(job.id, sc.channel_id, digest_cursor=cursor, digested=digested)
                await self._update_progress(job)
            await self._mark(job.id, sc.channel_id, digest_done=True)

    async def _wait_for_budget(self, job: ScanJob) -> None:
        while (reason := self.budget.blocked_reason(None)):
            self._phase_note[job.guild_id] = (
                "used today's free AI allowance for history; continuing tomorrow" if "daily" in reason
                else "pacing AI calls")
            await self._update_progress(job, force=True)
            await asyncio.sleep(600 if "daily" in reason else 20)

    async def _mark(self, job_id: int, channel_id: int, **fields) -> None:
        async with self.db.session() as s:
            row = await s.get(ScanChannel, (job_id, channel_id))
            for k, v in fields.items():
                setattr(row, k, v)
