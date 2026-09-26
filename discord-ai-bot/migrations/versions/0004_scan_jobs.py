"""scan_jobs + scan_channels (resumable /scanserver)

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-26
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "scan_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("guild_id", sa.BigInteger(), sa.ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("phase", sa.String(20), nullable=False),
        sa.Column("started_by", sa.BigInteger(), nullable=False),
        sa.Column("progress_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("progress_message_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_index("ix_scan_jobs_guild_id", "scan_jobs", ["guild_id"])
    op.create_table(
        "scan_channels",
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("scan_jobs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("channel_id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("estimate", sa.Integer(), nullable=False),
        sa.Column("fetched", sa.Integer(), nullable=False),
        sa.Column("fetch_cursor", sa.BigInteger(), nullable=False),
        sa.Column("fetch_done", sa.Boolean(), nullable=False),
        sa.Column("digest_cursor", sa.BigInteger(), nullable=False),
        sa.Column("digested", sa.Integer(), nullable=False),
        sa.Column("digest_done", sa.Boolean(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("scan_channels")
    op.drop_index("ix_scan_jobs_guild_id", "scan_jobs")
    op.drop_table("scan_jobs")
