"""Owner sessions and persistent login throttling."""
from alembic import op
import sqlalchemy as sa

revision = 'db71ea6c903f'
down_revision = 'ca294b816edf'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('web_sessions',
        sa.Column('token_hash',sa.String(64),primary_key=True),
        sa.Column('owner_id',sa.String(64),sa.ForeignKey('profiles.id'),nullable=False),
        sa.Column('credential_version',sa.String(64),nullable=False),
        sa.Column('csrf_token',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('revoked',sa.Boolean(),nullable=False,server_default='false'))
    op.create_index('ix_web_sessions_owner_id','web_sessions',['owner_id'])
    op.create_index('ix_web_sessions_expires_at','web_sessions',['expires_at'])
    op.create_table('login_throttles',
        sa.Column('bucket_key',sa.String(64),primary_key=True),
        sa.Column('owner_id',sa.String(64),sa.ForeignKey('profiles.id'),nullable=False),
        sa.Column('window_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('failures',sa.Integer(),nullable=False))
    op.create_index('ix_login_throttles_owner_id','login_throttles',['owner_id'])


def downgrade():
    op.drop_table('login_throttles')
    op.drop_table('web_sessions')
