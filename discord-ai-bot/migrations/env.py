"""Alembic migration runner (synchronous SQLite connection)."""
from alembic import context
from sqlalchemy import engine_from_config, pool

from bot.database.models import Base

config = context.config
target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    # The FTS5 search tables are managed by hand in migrations, not by models.py.
    return not (type_ == "table" and name.startswith("messages_fts"))


def run_migrations_online() -> None:
    engine = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with engine.connect() as connection:
        # render_as_batch lets future migrations alter columns on SQLite
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True,
                          include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
