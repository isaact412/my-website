"""How strong a memory is: evidence pushes it up the ladder, time wears it down.

temporary → useful → established → lore
"""
from datetime import datetime, timezone

# Days until a memory's strength halves if nothing reinforces it.
HALF_LIFE_DAYS = {"temporary": 3, "useful": 30, "established": 180, "lore": 3650}


def tier(m) -> str:
    if m.pinned or (m.kind == "lore" and m.importance >= 3 and m.times_reinforced >= 3):
        return "lore"
    if m.times_reinforced >= 6 and m.distinct_days >= 3:
        return "established"
    if m.times_reinforced >= 2 or m.kind == "lore":
        return "useful"
    return "temporary"


def strength(m, now: datetime | None = None) -> float:
    """0..1. Importance × confidence × time decay."""
    now = now or datetime.now(timezone.utc)
    updated = m.updated_at if m.updated_at.tzinfo else m.updated_at.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - updated).total_seconds() / 86400)
    decay = 0.5 ** (age_days / HALF_LIFE_DAYS[tier(m)])
    return (m.importance / 3) * m.confidence * decay
