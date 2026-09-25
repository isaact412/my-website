"""messages table + full-text search index

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("guild_id", sa.BigInteger(), sa.ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("author_id", sa.BigInteger(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("reply_to_id", sa.BigInteger(), nullable=True),
        sa.Column("attachment_count", sa.Integer(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("edited_at", TS, nullable=True),
    )
    op.create_index("ix_messages_author_id", "messages", ["author_id"])
    op.create_index("ix_messages_guild_channel_created", "messages", ["guild_id", "channel_id", "created_at"])

    # SQLite FTS5 full-text index, kept in sync with `messages` by triggers.
    op.execute(
        "CREATE VIRTUAL TABLE messages_fts USING fts5("
        "content, content='messages', content_rowid='id', tokenize='unicode61 remove_diacritics 2')"
    )
    op.execute(
        "CREATE TRIGGER messages_fts_insert AFTER INSERT ON messages BEGIN "
        "INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content); END"
    )
    op.execute(
        "CREATE TRIGGER messages_fts_delete AFTER DELETE ON messages BEGIN "
        "INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.id, old.content); END"
    )
    op.execute(
        "CREATE TRIGGER messages_fts_update AFTER UPDATE OF content ON messages BEGIN "
        "INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.id, old.content); "
        "INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content); END"
    )


def downgrade() -> None:
    for trigger in ("messages_fts_insert", "messages_fts_delete", "messages_fts_update"):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    op.execute("DROP TABLE IF EXISTS messages_fts")
    op.drop_index("ix_messages_guild_channel_created", "messages")
    op.drop_index("ix_messages_author_id", "messages")
    op.drop_table("messages")
