"""Regression tests for alert evaluation.

Guards the quoted-key f-string fixes in evaluate_alerts: before the fix
every alert path raised NameError at runtime (swallowed by the caller),
so budget, latency, and low-cache-hit notifications never fired.
"""
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from promptcache.production import alerts

WORKSPACES_DDL = """
CREATE TABLE workspaces (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_id INTEGER, name TEXT, tenant_id TEXT,
  alerts_enabled BOOLEAN DEFAULT 1,
  budget_alert_percent INTEGER DEFAULT 80,
  latency_alert_ms INTEGER DEFAULT 100,
  cache_hit_alert_percent INTEGER DEFAULT 50,
  webhook_url_encrypted TEXT,
  monthly_budget NUMERIC DEFAULT 100,
  rate_limit_per_minute INTEGER DEFAULT 60,
  max_retries INTEGER DEFAULT 1,
  timeout_seconds INTEGER DEFAULT 30
)
"""
USAGE_DDL = """
CREATE TABLE usage_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id TEXT, provider TEXT, cached BOOLEAN,
  actual_cost NUMERIC, baseline_cost NUMERIC, saved NUMERIC,
  latency_ms INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""
NOTIFICATIONS_DDL = """
CREATE TABLE notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id TEXT, kind TEXT, title TEXT, message TEXT,
  severity TEXT DEFAULT 'info', read_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""


class AlertNotificationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        with self.engine.begin() as conn:
            conn.execute(text(WORKSPACES_DDL))
            conn.execute(text(USAGE_DDL))
            conn.execute(text(NOTIFICATIONS_DDL))
        self.session = Session(self.engine)
        self.session.execute(text("INSERT INTO workspaces (tenant_id, name, owner_id) VALUES ('ws_1', 'Acme', 1)"))
        self.session.commit()
        # NOTE: addCleanup is LIFO. The engine must be disposed only AFTER the
        # session is closed, otherwise session.close() tries to roll back on an
        # already-closed connection ("Cannot operate on a closed database").
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.session.close)

    def _notifications(self):
        return self.session.execute(text("SELECT kind, message FROM notifications ORDER BY id")).all()

    def _healthy_policy(self):
        return {"monthly_budget": 100.0, "spent_this_month": 1.0,
                "rate_limit_per_minute": 60, "max_retries": 1, "timeout_seconds": 30}

    def test_budget_threshold_alert_fires(self):
        policy = self._healthy_policy()
        policy["spent_this_month"] = 90.0
        with patch.object(alerts, "get_policy", return_value=policy):
            alerts.evaluate_alerts(self.session, "ws_1", latency_ms=10)
        rows = self._notifications()
        self.assertEqual([r[0] for r in rows], ["budget"])
        self.assertIn("90.00", rows[0][1])
        self.assertIn("100.00", rows[0][1])

    def test_latency_threshold_alert_fires(self):
        with patch.object(alerts, "get_policy", return_value=self._healthy_policy()):
            alerts.evaluate_alerts(self.session, "ws_1", latency_ms=250)
        rows = self._notifications()
        self.assertEqual([r[0] for r in rows], ["latency"])
        self.assertIn("250", rows[0][1])

    def test_low_cache_hit_rate_alert_fires(self):
        with patch.object(alerts, "get_policy", return_value=self._healthy_policy()):
            for _ in range(10):
                self.session.execute(text(
                    "INSERT INTO usage_events (tenant_id, provider, cached, actual_cost, baseline_cost, saved, latency_ms) "
                    "VALUES ('ws_1', 'mock', 0, 0.01, 0.01, 0, 5)"))
            self.session.commit()
            alerts.evaluate_alerts(self.session, "ws_1", latency_ms=10)
        rows = self._notifications()
        self.assertEqual([r[0] for r in rows], ["cache"])
        self.assertIn("cache hit rate", rows[0][1].lower())

    def test_no_alert_when_policy_healthy(self):
        with patch.object(alerts, "get_policy", return_value=self._healthy_policy()):
            alerts.evaluate_alerts(self.session, "ws_1", latency_ms=10)
        self.assertEqual(self._notifications(), [])


if __name__ == "__main__":
    unittest.main()