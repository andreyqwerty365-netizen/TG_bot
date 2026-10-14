"""Owner can pause interpretation and lower its configured spend ceiling."""
from alembic import op
import sqlalchemy as sa

revision = "e41978d2ab67"
down_revision = "d721cde40377"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("profiles", sa.Column("ai_paused", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("profiles", sa.Column("ai_budget_cap_micro_usd", sa.BigInteger(), nullable=True))


def downgrade():
    op.drop_column("profiles", "ai_budget_cap_micro_usd")
    op.drop_column("profiles", "ai_paused")
