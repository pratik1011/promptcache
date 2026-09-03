"""Savings-based platform fee: share percentage, cap, and Stripe billing."""
import os
import unittest
from datetime import datetime, timedelta, UTC
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from promptcache.production.billing import accrue_savings_fee, billing_summary, savings_fee_summary

DDL = [
    """
CREATE TABLE users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  plan TEXT NOT NULL DEFAULT 'developer',
  subscription_status TEXT NOT NULL DEFAULT 'free',
  stripe_customer_id TEXT,
  stripe_subscription_id TEXT,
  current_period_end TIMESTAMP
)
""",
    """
CREATE TABLE workspaces (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_id INTEGER,
  name TEXT,
  tenant_id TEXT UNIQUE
)
""",
    """
CREATE TABLE usage_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  cached BOOLEAN NOT NULL,
  actual_cost NUMERIC NOT NULL,
  baseline_cost NUMERIC NOT NULL,
  saved NUMERIC NOT NULL,
  latency_ms INTEGER NOT NULL,
  created_at TIMESTAMP
)
""",
    """
CREATE TABLE fee_accruals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  month TEXT NOT NULL,
  accrued NUMERIC NOT NULL DEFAULT 0,
  currency TEXT NOT NULL DEFAULT 'usd',
  last_accrued_at TIMESTAMP,
  UNIQUE (user_id, month)
)
""",
]


def _register_adapter():
    import sqlite3
    sqlite3.register_adapter(datetime, lambda value: value.isoformat(sep=" "))


_register_adapter()


class SavingsFeeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        with self.engine.begin() as conn:
            for statement in DDL:
                conn.execute(text(statement))
            conn.execute(text(
                "INSERT INTO users (email, password_hash) VALUES ('a@b.co', 'x')"))
            conn.execute(text(
                "INSERT INTO workspaces (owner_id, name, tenant_id) VALUES (1, 'ws', 't1')"))
            now = datetime.now(UTC)
            for saved in (1.5, 2.5, 6.0):
                conn.execute(text(
                    "INSERT INTO usage_events (tenant_id, provider, cached, actual_cost,"
                    " baseline_cost, saved, latency_ms, created_at)"
                    " VALUES ('t1', 'p', 0, 0, 0, :s, 1, :ts)"),
                    {"s": saved, "ts": (now - timedelta(days=1)).isoformat(sep=" ")})
            # old savings from two months ago must not count
            conn.execute(text(
                "INSERT INTO usage_events (tenant_id, provider, cached, actual_cost,"
                " baseline_cost, saved, latency_ms, created_at)"
                " VALUES ('t1', 'p', 0, 0, 0, 99, 1, :ts)"),
                {"ts": (now - timedelta(days=45)).isoformat(sep=" ")})
        self.session = Session(self.engine)
        self.addCleanup(self.session.close)

    def test_fee_is_share_of_monthly_savings(self):
        with patch.dict(os.environ, {"SAVINGS_SHARE_PERCENT": "10", "PLATFORM_FEE_CAP": "0"}):
            summary = savings_fee_summary(self.session, 1)
        self.assertAlmostEqual(summary["savings_this_month"], 10.0)
        self.assertAlmostEqual(summary["platform_fee"], 1.0)
        self.assertEqual(summary["savings_share_percent"], 10)

    def test_fee_is_zero_when_share_disabled(self):
        with patch.dict(os.environ, {"SAVINGS_SHARE_PERCENT": "0"}):
            summary = savings_fee_summary(self.session, 1)
        self.assertAlmostEqual(summary["platform_fee"], 0.0)

    def test_cap_limits_fee(self):
        with patch.dict(os.environ, {"SAVINGS_SHARE_PERCENT": "10", "PLATFORM_FEE_CAP": "0.50"}):
            summary = savings_fee_summary(self.session, 1)
        self.assertAlmostEqual(summary["platform_fee"], 0.50)
        self.assertEqual(summary["platform_fee_cap"], 0.50)

    def test_old_savings_excluded(self):
        with patch.dict(os.environ, {"SAVINGS_SHARE_PERCENT": "10", "PLATFORM_FEE_CAP": "0"}):
            summary = savings_fee_summary(self.session, 1)
        self.assertAlmostEqual(summary["savings_this_month"], 10.0, places=2)

    def test_billing_summary_includes_savings_fee(self):
        summary = billing_summary(self.session, 1)
        self.assertIn("savings_fee", summary)
        self.assertIn("platform_fee", summary["savings_fee"])


class AccrualTests(unittest.TestCase):
    """accrue_savings_fee creates a Stripe invoice item for the unbilled delta,
    and the fee_accruals ledger prevents double-billing. Deltas under one cent
    are skipped."""

    def setUp(self):
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        with self.engine.begin() as conn:
            for statement in DDL:
                conn.execute(text(statement))
            conn.execute(text(
                "INSERT INTO users (email, password_hash, stripe_customer_id)"
                " VALUES ('a@b.co', 'x', 'cus_test123')"))
            conn.execute(text(
                "INSERT INTO workspaces (owner_id, name, tenant_id) VALUES (1, 'ws', 't1')"))
            now = datetime.now(UTC)
            for saved in (1.5, 2.5, 6.0):  # total $10 saved this month
                conn.execute(text(
                    "INSERT INTO usage_events (tenant_id, provider, cached, actual_cost,"
                    " baseline_cost, saved, latency_ms, created_at)"
                    " VALUES ('t1', 'p', 0, 0, 0, :s, 1, :ts)"),
                    {"s": saved, "ts": (now - timedelta(days=1)).isoformat(sep=" ")})
        self.session = Session(self.engine)
        self.addCleanup(self.session.close)

    @patch("promptcache.production.billing._stripe_post")
    def test_accrue_bills_unbilled_delta(self, mock_post):
        mock_post.return_value = {"id": "ii_test456", "object": "invoiceitem"}
        with patch.dict(os.environ, {"SAVINGS_SHARE_PERCENT": "10", "PLATFORM_FEE_CAP": "0",
                                     "STRIPE_SECRET_KEY": "sk_test_x"}):
            result = accrue_savings_fee(self.session, 1)
        self.assertTrue(result["accrued"])
        self.assertAlmostEqual(result["billed_now"], 1.0)  # 10% of $10 = $1.00
        self.assertEqual(result["invoice_item_id"], "ii_test456")
        mock_post.assert_called_once()
        # ledger recorded the accrual
        accrued = self.session.execute(
            text("SELECT accrued FROM fee_accruals WHERE user_id=1")).scalar()
        self.assertAlmostEqual(float(accrued), 1.0)

    @patch("promptcache.production.billing._stripe_post")
    def test_accrue_is_idempotent(self, mock_post):
        mock_post.return_value = {"id": "ii_first"}
        env = {"SAVINGS_SHARE_PERCENT": "10", "PLATFORM_FEE_CAP": "0", "STRIPE_SECRET_KEY": "sk_test_x"}
        with patch.dict(os.environ, env):
            first = accrue_savings_fee(self.session, 1)
            second = accrue_savings_fee(self.session, 1)
        self.assertTrue(first["accrued"])
        self.assertFalse(second["accrued"])  # already accrued, nothing to bill
        self.assertAlmostEqual(second["billed_now"], 0.0)
        self.assertEqual(mock_post.call_count, 1)  # only one invoice item

    def test_accrue_no_op_without_stripe(self):
        with patch.dict(os.environ, {"STRIPE_SECRET_KEY": ""}):
            result = accrue_savings_fee(self.session, 1)
        self.assertFalse(result["accrued"])
        self.assertAlmostEqual(result["billed_now"], 0.0)
        self.assertEqual(result.get("reason"), "stripe_not_configured")

    def test_accrue_no_op_without_customer(self):
        # remove the stripe customer from the user
        self.session.execute(text("UPDATE users SET stripe_customer_id=NULL WHERE id=1"))
        self.session.commit()
        with patch.dict(os.environ, {"STRIPE_SECRET_KEY": "sk_test_x"}):
            result = accrue_savings_fee(self.session, 1)
        self.assertFalse(result["accrued"])
        self.assertEqual(result.get("reason"), "no_billing_account")


if __name__ == "__main__":
    unittest.main()
