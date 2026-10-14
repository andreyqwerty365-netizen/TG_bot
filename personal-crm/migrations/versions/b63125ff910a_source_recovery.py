"""Persist bounded source-processing recovery without altering existing records."""
from alembic import op
import sqlalchemy as sa

revision = "b63125ff910a"
down_revision = "24b831882dea"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("source_versions", sa.Column("parse_attempts", sa.Integer(), server_default="0", nullable=False))
    op.add_column("source_versions", sa.Column("retry_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("source_versions", "retry_at")
    op.drop_column("source_versions", "parse_attempts")
