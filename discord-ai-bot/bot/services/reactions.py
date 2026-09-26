"""Emoji reactions picked by simple rules. Free: no AI involved."""
import random
import re

RULES = [
    (re.compile(r"lmao|lmfao|\bdead\b|i'?m crying|💀|☠️", re.I), ["💀", "😭"]),
    (re.compile(r"😭|crying|\bpls\b|please no", re.I), ["😭", "💀"]),
    (re.compile(r"\bwhat\?+$|\bhuh\b|\bwtf\b|\?\?\?|why would", re.I), ["🤨", "❓"]),
    (re.compile(r"\b(i'?ll|i will|gonna|on it|trust me|tomorrow)\b", re.I), ["🫡", "🤨"]),
    (re.compile(r"\b(let'?s go+|w+ |huge w|goated|fire|🔥)\b", re.I), ["🔥"]),
    (re.compile(r"\b(lost|broke|failed|crashed|died|ratio|\bl\b)\b", re.I), ["💀", "👎"]),
]


def pick_reaction(text: str) -> str | None:
    for pattern, emojis in RULES:
        if pattern.search(text):
            return random.choice(emojis)
    return None
