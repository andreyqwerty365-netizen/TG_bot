"""Durable mailbox checkpoints, leases and message identity; no credentials."""
from alembic import op
import sqlalchemy as sa

revision = "f5029a13c47b"
down_revision = "e41978d2ab67"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("mail_accounts",
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("profiles.id"), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("account_key", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("cursor", sa.JSON()), sa.Column("lease_token", sa.String(36)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("next_sync_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(32)),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("saved_count", sa.Integer(), nullable=False),
        sa.Column("reset_count", sa.Integer(), nullable=False),
        sa.CheckConstraint("status IN ('disabled','idle','syncing','backoff','auth_error','error')"))
    op.create_table("mail_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("mail_accounts.owner_id"), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("thread_id", sa.String(64), nullable=False),
        sa.Column("message_id", sa.String(1000), nullable=False),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("pointer", sa.JSON()), sa.Column("flags", sa.JSON(), nullable=False),
        sa.Column("removed", sa.Boolean(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "key"))
    for column in ("owner_id", "thread_id", "source_id"):
        op.create_index(f"ix_mail_messages_{column}", "mail_messages", [column])


def downgrade():
    op.drop_table("mail_messages")
    op.drop_table("mail_accounts")
