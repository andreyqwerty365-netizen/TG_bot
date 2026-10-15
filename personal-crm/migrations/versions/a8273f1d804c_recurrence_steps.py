"""Calendar series, one open instance and confirmed child plans."""
from alembic import op
import sqlalchemy as sa

revision = "a8273f1d804c"
down_revision = "f5029a13c47b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("recurrences",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column("frequency", sa.String(16), nullable=False), sa.Column("interval", sa.Integer(), nullable=False),
        sa.Column("anchor_on", sa.Date(), nullable=False), sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("reminder_time", sa.String(5)), sa.Column("template", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("frequency IN ('daily','weekly','monthly')", name="ck_recurrence_frequency"),
        sa.CheckConstraint("interval BETWEEN 1 AND 365", name="ck_recurrence_interval"),
        sa.CheckConstraint("status IN ('active','stopped')", name="ck_recurrence_status"))
    op.create_index("ix_recurrences_owner_id", "recurrences", ["owner_id"])
    op.create_table("recurrence_history",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column("recurrence_id", sa.String(36), sa.ForeignKey("recurrences.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("before", sa.JSON()),
        sa.Column("after", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("recurrence_id", "version"))
    for field in ("owner_id", "recurrence_id"):
        op.create_index(f"ix_recurrence_history_{field}", "recurrence_history", [field])
    for name, kind in [("recurrence_id", sa.String(36)), ("occurrence_on", sa.Date()), ("occurrence_timezone", sa.String(64)),
                       ("recurrence_warning", sa.String(32)), ("parent_task_id", sa.String(36)),
                       ("step_batch", sa.Integer()), ("step_index", sa.Integer()), ("promoted_steps_revision", sa.Integer())]:
        op.add_column("tasks", sa.Column(name, kind))
    op.add_column("tasks", sa.Column("steps_revision", sa.Integer(), nullable=False, server_default="1"))
    op.create_foreign_key("fk_tasks_recurrence", "tasks", "recurrences", ["recurrence_id"], ["id"])
    op.create_foreign_key("fk_tasks_parent", "tasks", "tasks", ["parent_task_id"], ["id"])
    op.create_index("ix_tasks_recurrence_id", "tasks", ["recurrence_id"])
    op.create_index("ix_tasks_parent_task_id", "tasks", ["parent_task_id"])
    op.create_unique_constraint("uq_recurrence_occurrence", "tasks", ["recurrence_id", "occurrence_on"])
    op.create_unique_constraint("uq_plan_child", "tasks", ["parent_task_id", "step_batch", "step_index"])
    op.create_index("uq_recurrence_open", "tasks", ["recurrence_id"], unique=True,
                    postgresql_where=sa.text("recurrence_id IS NOT NULL AND state IN ('active','in_progress','deferred')"))


def downgrade():
    for name in ("uq_recurrence_open", "ix_tasks_parent_task_id", "ix_tasks_recurrence_id"):
        op.drop_index(name, table_name="tasks")
    for name in ("uq_plan_child", "uq_recurrence_occurrence", "fk_tasks_parent", "fk_tasks_recurrence"):
        op.drop_constraint(name, "tasks")
    for field in ("recurrence_id", "occurrence_on", "occurrence_timezone", "recurrence_warning", "parent_task_id",
                  "step_batch", "step_index", "steps_revision", "promoted_steps_revision"):
        op.drop_column("tasks", field)
    op.drop_table("recurrence_history")
    op.drop_table("recurrences")
