"""Savings-based platform fee: share percentage, cap, and billing summary wiring."""
import os
import unittest
from datetime import datetime, timedelta, UTC
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from promptcache.production.billing import billing_summary, savings_fee_summary

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
)""",
    """
CREATE TABLE workspaces (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_id INTEGER,
  name TEXT,
  tenant_id TEXT UNIQUE
)""",
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
)""",
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
        self.assertEqual(summary["savings_share_percent"], 10.0)
        self.assertIsNone(summary["platform_fee_cap"])

    def test_cap_limits_the_fee(self):
        with patch.dict(os.environ, {"SAVINGS_SHARE_PERCENT": "50", "PLATFORM_FEE_CAP": "2"}):
            summary = savings_fee_summary(self.session, 1)
        self.assertAlmostEqual(summary["platform_fee"], 2.0)
        self.assertAlmostEqual(summary["platform_fee_cap"], 2.0)

    def test_zero_share_disables_the_fee(self):
        with patch.dict(os.environ, {"SAVINGS_SHARE_PERCENT": "0"}):
            summary = savings_fee_summary(self.session, 1)
        self.assertAlmostEqual(summary["platform_fee"], 0.0)

    def test_billing_summary_includes_savings_fee(self):
        with patch.dict(os.environ, {"SAVINGS_SHARE_PERCENT": "10", "PLATFORM_FEE_CAP": "0"}):
            summary = billing_summary(self.session, 1)
        self.assertIn("savings_fee", summary)
        self.assertAlmostEqual(summary["savings_fee"]["platform_fee"], 1.0)
        self.assertEqual(summary["plan"], "developer")


if __name__ == "__main__":
    unittest.main()
