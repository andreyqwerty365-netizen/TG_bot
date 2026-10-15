"""Fence restored profiles until an explicit offline review."""
from alembic import op
import sqlalchemy as sa

revision = "ca294b816edf"
down_revision = "b9184f723ade"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("profiles", sa.Column("recovery_hold", sa.Boolean(), nullable=False, server_default="false"))


def downgrade():
    op.drop_column("profiles", "recovery_hold")
