"""Console + file logging, with secrets scrubbed out of every line."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


class RedactSecrets(logging.Filter):
    """Replaces any secret value with *** before a log line is written."""

    def __init__(self, secrets: list[str]):
        super().__init__()
        self.secrets = [s for s in secrets if s]

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for secret in self.secrets:
            message = message.replace(secret, "***")
        record.msg, record.args = message, None
        return True


def setup_logging(level: str, secrets: list[str]) -> None:
    Path("logs").mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%H:%M:%S")

    console = logging.StreamHandler()
    file = RotatingFileHandler("logs/bot.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")

    root = logging.getLogger()
    root.setLevel(level)
    for handler in (console, file):
        handler.setFormatter(fmt)
        handler.addFilter(RedactSecrets(secrets))
        root.addHandler(handler)

    # discord.py is very chatty at INFO; keep its noise down
    logging.getLogger("discord").setLevel(logging.WARNING)
