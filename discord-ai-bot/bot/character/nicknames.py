"""Who's who: real names and nicknames for server members, from config/nicknames.yaml."""
import logging
from pathlib import Path

import yaml

log = logging.getLogger("bot.character")

PATH = Path(__file__).resolve().parents[2] / "config" / "nicknames.yaml"


class Nicknames:
    def __init__(self, path: Path = PATH):
        self.path = path
        self._mtime = None
        self._data: dict[str, list[str]] = {}

    def _load(self) -> dict[str, list[str]]:
        """Re-reads the file whenever it changes, so edits apply without a restart."""
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return {}
        if mtime != self._mtime:
            try:
                raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
                self._data = {str(k): [str(a) for a in (v or [])] for k, v in raw.items()}
            except (OSError, yaml.YAMLError) as e:
                log.warning("Couldn't read %s (%s); keeping the previous version", self.path.name, e)
            self._mtime = mtime
        return self._data

    def real_name(self, *names: str | None) -> str | None:
        """The real name for any of these Discord names, or None."""
        wanted = {n.lower() for n in names if n}
        for real, aliases in self._load().items():
            if real.lower() in wanted or wanted & {a.lower() for a in aliases}:
                return real
        return None

    def whos_who(self) -> list[str]:
        """Lines like 'dale = Massage fucking Watson / watson' for the prompt."""
        return [f"{real} = {' / '.join(aliases)}" if aliases else real for real, aliases in self._load().items()]
