import sqlalchemy as sa
from alembic import op


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'cache_records',
        sa.Column('semantic_scope', sa.String(length=64), nullable=False, server_default='legacy-unscoped'),
    )
    op.create_index(
        'cache_records_scope_idx',
        'cache_records',
        ['tenant_id', 'cache_namespace', 'semantic_scope'],
    )


def downgrade() -> None:
    op.drop_index('cache_records_scope_idx', table_name='cache_records')
    op.drop_column('cache_records', 'semantic_scope')
