"""Version-bound suggestions and an explicitly approved future reminder preference."""
from alembic import op
import sqlalchemy as sa

revision = "b9184f723ade"
down_revision = "a8273f1d804c"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("profiles", sa.Column("preferred_reminder_time", sa.String(5)))
    op.create_table("planning_suggestions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id")),
        sa.Column("task_version", sa.Integer()), sa.Column("profile_version", sa.Integer()),
        sa.Column("kind", sa.String(16), nullable=False), sa.Column("event_key", sa.String(128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "event_key"),
        sa.CheckConstraint("kind IN ('early','step','reminder_time')", name="ck_planning_kind"),
        sa.CheckConstraint("status IN ('pending','accepted','dismissed','stale')", name="ck_planning_status"))
    for field in ("owner_id", "task_id"):
        op.create_index(f"ix_planning_suggestions_{field}", "planning_suggestions", [field])


def downgrade():
    op.drop_table("planning_suggestions")
    op.drop_column("profiles", "preferred_reminder_time")
