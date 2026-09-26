"""scan_chunks: prioritized conversations for learning lore from history

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-26
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scan_chunks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("scan_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("start_id", sa.BigInteger(), nullable=False),
        sa.Column("end_id", sa.BigInteger(), nullable=False),
        sa.Column("n_messages", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("done", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_scan_chunks_job_todo", "scan_chunks", ["job_id", "done", "score"])


def downgrade() -> None:
    op.drop_index("ix_scan_chunks_job_todo", "scan_chunks")
    op.drop_table("scan_chunks")
