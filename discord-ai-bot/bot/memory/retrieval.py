"""Picks the few memories worth including in a reply. Never dumps the whole database."""
import random
from datetime import datetime, timedelta, timezone

import numpy as np

from bot.memory import store
from bot.memory.embeddings import Embedder, from_blob
from bot.memory.strength import strength

MAX_PEOPLE_MEMORIES = 6
MAX_LORE = 2
LORE_MIN_RELEVANCE = 0.55       # lore must actually relate to the conversation
CALLBACK_COOLDOWN = timedelta(hours=6)


async def relevant_memories(s, embedder: Embedder, guild_id: int, participant_ids: list[int],
                            conversation: str, callback_chance: float, opted_out) -> dict[str, list]:
    """Returns {"people": [...], "lore": [...]} of Memory rows."""
    memories = [m for m in await store.active_memories(s, guild_id)
                if not any(opted_out(uid) for uid in store.subject_ids(m))]
    if not memories:
        return {"people": [], "lore": []}

    qv = (await embedder.embed([conversation[-1500:]]) or [None])[0]
    words = set(conversation.lower().split())
    now = datetime.now(timezone.utc)

    def relevance(m) -> float:
        mv = from_blob(m.embedding)
        if qv is not None and mv is not None:
            return float(np.dot(qv, mv))
        return store.matches_keywords(m, words)

    # People: memories about whoever is in the conversation, most relevant + strongest first.
    people_scored = []
    for m in memories:
        if m.kind in ("member", "relationship") and set(store.subject_ids(m)) & set(participant_ids):
            people_scored.append((0.6 * relevance(m) + 0.4 * strength(m, now), m))
    people = [m for _, m in sorted(people_scored, key=lambda x: x[0], reverse=True)[:MAX_PEOPLE_MEMORIES]]

    # Lore: only when it genuinely relates, wasn't used recently, and the dice say so.
    lore = []
    for m in memories:
        if m.kind != "lore":
            continue
        rel = relevance(m)
        recent = m.last_referenced and (now - _aware(m.last_referenced)) < CALLBACK_COOLDOWN
        if rel >= LORE_MIN_RELEVANCE and not recent:
            lore.append((rel + 0.2 * strength(m, now), m))
    lore = [m for _, m in sorted(lore, key=lambda x: x[0], reverse=True)[:MAX_LORE]]
    if lore and random.random() > callback_chance:
        lore = []
    return {"people": people, "lore": lore}


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
