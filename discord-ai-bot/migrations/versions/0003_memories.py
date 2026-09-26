"""memories + memory_sources

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-26
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "memories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("guild_id", sa.BigInteger(), sa.ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("subject_ids", sa.String(200), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("keywords", sa.String(300), nullable=False),
        sa.Column("importance", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("times_reinforced", sa.Integer(), nullable=False),
        sa.Column("distinct_days", sa.Integer(), nullable=False),
        sa.Column("last_seen_day", sa.String(10), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("embedding", sa.LargeBinary(), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.Column("last_referenced", TS, nullable=True),
    )
    op.create_index("ix_memories_guild_kind", "memories", ["guild_id", "kind", "active"])
    op.create_table(
        "memory_sources",
        sa.Column("memory_id", sa.Integer(), sa.ForeignKey("memories.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("message_id", sa.BigInteger(), primary_key=True),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("author_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("ix_memory_sources_author_id", "memory_sources", ["author_id"])


def downgrade() -> None:
    op.drop_index("ix_memory_sources_author_id", "memory_sources")
    op.drop_table("memory_sources")
    op.drop_index("ix_memories_guild_kind", "memories")
    op.drop_table("memories")
