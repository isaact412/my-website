"""initial tables: guilds, users, names, settings, usage

Revision ID: 0001
Revises:
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "guilds",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("first_seen", TS, nullable=False),
        sa.Column("last_seen", TS, nullable=False),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("global_name", sa.String(100), nullable=True),
        sa.Column("first_seen", TS, nullable=False),
        sa.Column("last_seen", TS, nullable=False),
    )
    op.create_table(
        "user_names",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("value", sa.String(100), nullable=False),
        sa.Column("first_seen", TS, nullable=False),
        sa.Column("last_seen", TS, nullable=False),
        sa.UniqueConstraint("user_id", "guild_id", "kind", "value"),
    )
    op.create_index("ix_user_names_user_id", "user_names", ["user_id"])
    op.create_table(
        "guild_settings",
        sa.Column("guild_id", sa.BigInteger(), sa.ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("chattiness", sa.Integer(), nullable=False),
        sa.Column("roast_level", sa.Integer(), nullable=False),
        sa.Column("personality_json", sa.Text(), nullable=False),
        sa.Column("bot_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("memory_enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_table(
        "channel_settings",
        sa.Column("channel_id", sa.BigInteger(), primary_key=True),
        sa.Column("guild_id", sa.BigInteger(), sa.ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("excluded", sa.Boolean(), nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_index("ix_channel_settings_guild_id", "channel_settings", ["guild_id"])
    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.BigInteger(), primary_key=True),
        sa.Column("guild_id", sa.BigInteger(), primary_key=True),
        sa.Column("opted_out", sa.Boolean(), nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_table(
        "usage_stats",
        sa.Column("day", sa.String(10), primary_key=True),
        sa.Column("guild_id", sa.BigInteger(), primary_key=True),
        sa.Column("provider", sa.String(40), primary_key=True),
        sa.Column("model", sa.String(120), primary_key=True),
        sa.Column("kind", sa.String(30), primary_key=True),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("rate_limited", sa.Integer(), nullable=False),
        sa.Column("errors", sa.Integer(), nullable=False),
        sa.Column("paid_calls", sa.Integer(), nullable=False),
        sa.Column("est_cost_usd", sa.Float(), nullable=False),
    )


def downgrade() -> None:
    for table in ("usage_stats", "user_settings", "channel_settings", "guild_settings", "user_names", "users", "guilds"):
        op.drop_table(table)
