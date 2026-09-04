"""Baseline schema mirroring the SQLAlchemy models.

Fresh databases are also provisioned by initialize_database()
(Base.metadata.create_all); this baseline exists so versioned ALTER
migrations can follow. Future migrations should hand-write their DDL.

Revision ID: 0001
Revises:
Create Date: 2026-02-09

"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from promptcache.production.db import Base

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    from promptcache.production.db import Base

    Base.metadata.drop_all(bind=op.get_bind())
