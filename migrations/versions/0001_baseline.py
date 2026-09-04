"""Baseline schema mirroring the SQLAlchemy models.

Fresh databases are also provisioned by initialize_database()
(Base.metadata.create_all); this baseline exists so versioned ALTER
migrations can follow. Future migrations should hand-write their DDL.

Revision ID: 0001
Revises:
Create Date: 2026-02-09

"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from promptcache.production.db import Base

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(bind=op.get_bind())
    # Account tables are created below for later migration dependencies.
    op.create_table(
        'users',
        sa.Column('id', sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column('email', sa.Text(), nullable=False, unique=True),
        sa.Column('password_hash', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_table(
        'workspaces',
        sa.Column('id', sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column('owner_id', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('tenant_id', sa.Text(), nullable=False, unique=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_table(
        'api_keys',
        sa.Column('id', sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column('tenant_id', sa.Text(), nullable=False),
        sa.Column('key_hash', sa.Text(), nullable=False, unique=True),
        sa.Column('key_encrypted', sa.Text()),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('expires_at', sa.DateTime(timezone=True)),
        sa.Column('last_rotated_at', sa.DateTime(timezone=True)),
        sa.Column('last_revealed_at', sa.DateTime(timezone=True)),
    )
    op.create_index('api_keys_tenant_idx', 'api_keys', ['tenant_id'])


def downgrade() -> None:
    from promptcache.production.db import Base

    Base.metadata.drop_all(bind=op.get_bind())
