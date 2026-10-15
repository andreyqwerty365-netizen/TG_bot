"""Add projects and profile versions without rewriting task data."""
from alembic import op
import sqlalchemy as sa

revision = "c51d46c71af0"
down_revision = "b63125ff910a"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("profiles", sa.Column("version", sa.Integer(), server_default="1", nullable=False))
    op.create_table("projects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_projects_owner_id", "projects", ["owner_id"])
    op.add_column("tasks", sa.Column("project_id", sa.String(36), nullable=True))
    op.create_foreign_key("fk_tasks_project_id", "tasks", "projects", ["project_id"], ["id"])
    op.create_index("ix_tasks_project_id", "tasks", ["project_id"])


def downgrade():
    op.drop_index("ix_tasks_project_id", table_name="tasks")
    op.drop_constraint("fk_tasks_project_id", "tasks", type_="foreignkey")
    op.drop_column("tasks", "project_id")
    op.drop_index("ix_projects_owner_id", table_name="projects")
    op.drop_table("projects")
    op.drop_column("profiles", "version")
