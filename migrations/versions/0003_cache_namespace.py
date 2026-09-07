import sqlalchemy as sa
from alembic import op


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'cache_records',
        sa.Column('cache_namespace', sa.String(length=255), nullable=False, server_default='default'),
    )
    op.create_index(
        'cache_records_tenant_namespace_idx',
        'cache_records',
        ['tenant_id', 'cache_namespace'],
    )


def downgrade() -> None:
    op.drop_index('cache_records_tenant_namespace_idx', table_name='cache_records')
    op.drop_column('cache_records', 'cache_namespace')
