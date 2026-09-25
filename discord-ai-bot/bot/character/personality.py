"""Turns personality sliders into style instructions for the AI."""
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "personality.yaml"


@dataclass
class Personality:
    sliders: dict[str, int] = field(default_factory=dict)
    character: str = ""
    voice_examples: list[str] = field(default_factory=list)

    def level(self, name: str) -> int:
        return max(0, min(10, int(self.sliders.get(name, 5))))


def load_personality(path: Path = DEFAULT_PATH) -> Personality:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Personality(
        sliders=data.get("sliders", {}),
        character=(data.get("character") or "").strip(),
        voice_examples=list(data.get("voice_examples") or []),
    )


def _pick(level: int, low: str, mid: str, high: str) -> str:
    return low if level <= 3 else mid if level <= 6 else high


def style_rules(p: Personality) -> list[str]:
    """One short instruction per slider."""
    return [
        _pick(p.level("verbosity"),
              "keep it to 1-2 short sentences. a few words is often best.",
              "usually 1-3 sentences.",
              "you can ramble a bit, but never more than a short paragraph."),
        _pick(p.level("sarcasm"), "mostly sincere.", "a bit sarcastic.", "very sarcastic and dry."),
        _pick(p.level("chaos"), "stay on topic.", "occasionally take a weird angle.",
              "sometimes take a wildly unexpected but still relevant angle."),
        _pick(p.level("roasting"), "don't tease people.", "light teasing is fine.",
              "playful roasting is welcome, like friends do."),
        _pick(p.level("helpfulness"),
              "don't give advice unless someone begs.",
              "if someone genuinely asks for help, help briefly, then go back to being normal.",
              "if someone asks for help, give a real, useful answer."),
        _pick(p.level("slang"), "plain casual english.", "some internet slang.",
              "lots of internet/discord slang, but stay readable."),
        _pick(p.level("emoji"), "almost never use emoji.", "an emoji now and then.", "emoji are fine."),
        _pick(p.level("weirdness"), "be normal.", "be a little weirdly specific sometimes.",
              "be weirdly specific and oddly committed to bits."),
        _pick(p.level("raunchiness"),
              "keep it pretty clean.",
              "swearing and innuendo are fine.",
              "this is an adults' group chat: swear freely, be crude, dirty jokes and raunchy humor are welcome."),
        _pick(p.level("mirroring"),
              "use your own voice.",
              "loosely match the chat's vibe.",
              "talk the way the people in the chat log talk: copy their slang, spelling, swearing, "
              "caps/lowercase habits and message length. if they're crude, be crude back."),
    ]
