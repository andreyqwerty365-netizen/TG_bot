"""Persistent worker and externally verified backup state."""
from alembic import op
import sqlalchemy as sa

revision='ec82f6d410aa'
down_revision='db71ea6c903f'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('worker_status',
        sa.Column('owner_id',sa.String(64),sa.ForeignKey('profiles.id'),primary_key=True),
        sa.Column('role',sa.String(16),primary_key=True),sa.Column('state',sa.String(16),nullable=False),
        sa.Column('last_seen_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('last_success_at',sa.DateTime(timezone=True)),sa.Column('error_code',sa.String(32)),
        sa.CheckConstraint("role IN ('source','delivery','backup')",name='ck_worker_role'),
        sa.CheckConstraint("state IN ('running','idle','disabled','error')",name='ck_worker_state'))


def downgrade():
    op.drop_table('worker_status')
