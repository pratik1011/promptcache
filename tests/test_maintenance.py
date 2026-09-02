"""Pruning maintenance: expired cache entries and aged usage events are removed."""
import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from promptcache.production.repositories import prune_expired

# Raw DDL (SQLite-safe) mirroring the production tables the prune query touches.
CACHE_DDL = """
CREATE TABLE cache_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id TEXT NOT NULL,
  cache_key TEXT NOT NULL,
  prompt TEXT NOT NULL,
  response TEXT NOT NULL,
  embedding BLOB,
  provider TEXT NOT NULL,
  cost NUMERIC NOT NULL DEFAULT 0,
  created_at TIMESTAMP,
  expires_at TIMESTAMP
)
"""
USAGE_DDL = """
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
"""


class PruneTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        with self.engine.begin() as conn:
            conn.execute(text(CACHE_DDL))
            conn.execute(text(USAGE_DDL))
        self.session = Session(self.engine)
        self.now = datetime.now(timezone.utc)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.session.close)

    def _seed(self):
        self.session.execute(text(
            "INSERT INTO cache_records (tenant_id, cache_key, prompt, response, provider, cost, created_at, expires_at) "
            "VALUES ('ws_t', 'expired', 'p', '{}', 'mock', 0.01, :now, :past)"),
            {"now": self.now, "past": self.now - timedelta(seconds=1)})
        self.session.execute(text(
            "INSERT INTO cache_records (tenant_id, cache_key, prompt, response, provider, cost, created_at, expires_at) "
            "VALUES ('ws_t', 'alive', 'p', '{}', 'mock', 0.01, :now, :future)"),
            {"now": self.now, "future": self.now + timedelta(days=1)})
        self.session.execute(text(
            "INSERT INTO usage_events (tenant_id, provider, cached, actual_cost, baseline_cost, saved, latency_ms, created_at) "
            "VALUES ('ws_t', 'mock', 0, 0.01, 0.02, 0.01, 5, :old)"),
            {"old": self.now - timedelta(days=200)})
        self.session.execute(text(
            "INSERT INTO usage_events (tenant_id, provider, cached, actual_cost, baseline_cost, saved, latency_ms, created_at) "
            "VALUES ('ws_t', 'mock', 0, 0.01, 0.02, 0.01, 5, :now)"),
            {"now": self.now})
        self.session.commit()

    def test_prune_removes_expired_cache_and_old_usage(self):
        self._seed()
        result = prune_expired(self.session, event_retention_days=90)
        self.assertEqual(result["cache_records_deleted"], 1)
        self.assertEqual(result["usage_events_deleted"], 1)
        self.assertEqual(self.session.execute(text("SELECT count(*) FROM cache_records")).scalar(), 1)
        self.assertEqual(self.session.execute(text("SELECT count(*) FROM usage_events")).scalar(), 1)

    def test_prune_is_idempotent(self):
        self._seed()
        prune_expired(self.session, event_retention_days=90)
        result = prune_expired(self.session, event_retention_days=90)
        self.assertEqual(result["cache_records_deleted"], 0)
        self.assertEqual(result["usage_events_deleted"], 0)


if __name__ == "__main__":
    unittest.main()