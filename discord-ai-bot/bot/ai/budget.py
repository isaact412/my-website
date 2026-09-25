"""Anti-spam limits for AI calls. Kept below the free tiers' own limits."""
import time
from collections import deque
from datetime import date


class Budget:
    def __init__(self, per_minute: int, per_day: int, user_cooldown: int):
        self.per_minute = per_minute
        self.per_day = per_day
        self.user_cooldown = user_cooldown
        self._recent: deque[float] = deque()
        self._today = date.today()
        self._today_count = 0
        self._user_last: dict[int, float] = {}

    def _roll_day(self) -> None:
        if date.today() != self._today:
            self._today, self._today_count = date.today(), 0

    def blocked_reason(self, user_id: int | None) -> str | None:
        """Returns why a call isn't allowed right now, or None if it's fine."""
        now = time.monotonic()
        self._roll_day()
        while self._recent and now - self._recent[0] > 60:
            self._recent.popleft()
        if self._today_count >= self.per_day:
            return "daily limit reached"
        if len(self._recent) >= self.per_minute:
            return "per-minute limit reached"
        if user_id is not None and now - self._user_last.get(user_id, -1e9) < self.user_cooldown:
            return "user cooldown"
        return None

    def record(self, user_id: int | None) -> None:
        now = time.monotonic()
        self._recent.append(now)
        self._today_count += 1
        if user_id is not None:
            self._user_last[user_id] = now

    @property
    def calls_today(self) -> int:
        self._roll_day()
        return self._today_count
