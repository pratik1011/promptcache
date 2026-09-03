"""Savings-fee accrual ledger.

One row per (user, month) recording how much of the usage-based platform
fee has already been invoiced, so fee accrual is idempotent and only the
unbilled delta is sent to Stripe.

Revision ID: 0002
Revises: 0001
Create Date: 2026-02-09

"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fee_accruals",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("month", sa.String(7), nullable=False),
        sa.Column("accrued", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="usd"),
        sa.Column("last_accrued_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "month", name="fee_accruals_user_month_key"),
    )


def downgrade() -> None:
    op.drop_table("fee_accruals")