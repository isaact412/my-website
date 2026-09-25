"""Brings the database schema up to date on startup, backing it up first."""
import logging
import shutil
from datetime import datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

log = logging.getLogger("bot.db")

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config(db_path: Path) -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def current_revision(db_path: Path) -> str | None:
    if not db_path.exists():
        return None
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            return MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()


def upgrade_to_latest(db_path: Path) -> str:
    """Runs any pending migrations. Returns the schema version now in use."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = _alembic_config(db_path)
    head = ScriptDirectory.from_config(cfg).get_current_head()
    current = current_revision(db_path)

    if current == head:
        log.info("Database schema up to date (version %s)", head)
        return head

    if db_path.exists() and current is not None:
        backup_dir = db_path.parent / "backups"
        backup_dir.mkdir(exist_ok=True)
        backup = backup_dir / f"{db_path.stem}-{datetime.now():%Y%m%d-%H%M%S}.db"
        shutil.copy2(db_path, backup)
        log.info("Backed up database to %s before migrating", backup)

    log.info("Migrating database: %s -> %s", current or "empty", head)
    command.upgrade(cfg, "head")
    return head
