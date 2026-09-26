"""Message recall: finds real old messages related to the current conversation. 100% local.

Uses the SQLite full-text index over every stored message (including the whole scanned history),
so the bot can bring back what people actually said months ago without any AI call.
Only messages from channels everyone in the server can read are recalled, so nothing from a
private channel ever leaks into a public one.
"""
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from bot.database.models import Message

STOPWORDS = set("""
a about after again all also am an and any are as at be because been before being but by can could did do does
doing dont down during each few for from further had has have having he her here hers him his how i if im in into
is it its just like me more most my no nor not now of off on once only or other our out over own same she should so
some such than that thats the their them then there these they this those through to too under until up very was
we were what when where which while who whom why will with would you your yours yeah yea lol lmao bro ok okay oh
gonna wanna got get really thing things know think want need make going said say one two
""".split())


def keywords(conversation: str, limit: int = 8) -> list[str]:
    """The most distinctive words in the conversation (longer and rarer-looking words first)."""
    words = [w for w in re.findall(r"[a-z0-9']{3,}", conversation.lower()) if w not in STOPWORDS]
    seen, out = set(), []
    for w in sorted(words, key=len, reverse=True):
        w = w.strip("'")
        if w and w not in seen:
            seen.add(w)
            out.append(w)
    return out[:limit]


async def recall_messages(s, guild_id: int, conversation: str, public_channel_ids: set[int],
                          current_channel_id: int, limit: int = 8) -> list[Message]:
    words = keywords(conversation)
    if not words or not public_channel_ids:
        return []
    fts = " OR ".join(f'"{w}"' for w in words)
    ids = (await s.execute(
        text("SELECT rowid FROM messages_fts WHERE messages_fts MATCH :q ORDER BY rank LIMIT 300"), {"q": fts}
    )).scalars().all()
    if not ids:
        return []
    recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
    rows = list(await s.scalars(select(Message).where(
        Message.id.in_(ids), Message.guild_id == guild_id, Message.channel_id.in_(public_channel_ids))))
    order = {mid: i for i, mid in enumerate(ids)}
    picked, seen_text = [], set()
    for m in sorted(rows, key=lambda m: order[m.id]):
        created = m.created_at if m.created_at.tzinfo else m.created_at.replace(tzinfo=timezone.utc)
        if m.channel_id == current_channel_id and created > recent_cutoff:
            continue  # already in the live conversation
        key = m.content.lower().strip()
        if len(key.split()) < 3 or key in seen_text:
            continue  # skip one-word noise and duplicates
        seen_text.add(key)
        picked.append(m)
        if len(picked) >= limit:
            break
    return sorted(picked, key=lambda m: m.id)  # oldest first reads naturally
