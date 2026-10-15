"""Normalize titles independently of PostgreSQL's host locale."""
from alembic import op
import sqlalchemy as sa

revision = "d721cde40377"
down_revision = "c51d46c71af0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tasks", sa.Column("title_search", sa.Text(), server_default="", nullable=False))
    connection = op.get_bind()
    for identity, title in connection.execute(sa.text("SELECT id, title FROM tasks")):
        connection.execute(sa.text("UPDATE tasks SET title_search=:value WHERE id=:identity"),
                           {"identity": identity, "value": title.casefold()})


def downgrade():
    op.drop_column("tasks", "title_search")
