"""Pruning and daily-rollup maintenance for cache, usage, and rollup tables."""
import unittest
from datetime import datetime, timedelta, UTC

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from promptcache.production import repositories
from promptcache.production.repositories import UsageRepository, prune_expired, rollup_daily

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


ROLLUP_DDL = """
CREATE TABLE daily_usage_rollups (
  tenant_id TEXT NOT NULL,
  day DATE NOT NULL,
  provider TEXT NOT NULL,
  requests INTEGER NOT NULL DEFAULT 0,
  cache_hits INTEGER NOT NULL DEFAULT 0,
  actual_cost NUMERIC NOT NULL DEFAULT 0,
  baseline_cost NUMERIC NOT NULL DEFAULT 0,
  saved NUMERIC NOT NULL DEFAULT 0,
  PRIMARY KEY (tenant_id, day, provider)
)
"""
STATE_DDL = """
CREATE TABLE usage_rollup_state (
  tenant_id TEXT PRIMARY KEY,
  last_event_id INTEGER NOT NULL DEFAULT 0
)
"""


class PruneTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        with self.engine.begin() as conn:
            conn.execute(text(CACHE_DDL))
            conn.execute(text(USAGE_DDL))
            conn.execute(text(ROLLUP_DDL))
            conn.execute(text(STATE_DDL))
        self.session = Session(self.engine)
        self.now = datetime.now(UTC)
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


def _insert_event(session, tenant: str, cached: int, saved: float, when: datetime, provider: str = "mock"):
    session.execute(text(
        "INSERT INTO usage_events (tenant_id, provider, cached, actual_cost, baseline_cost, saved, latency_ms, created_at) "
        "VALUES (:tenant, :provider, :cached, 0.01, 0.02, :saved, 5, :when)"),
        {"tenant": tenant, "provider": provider, "cached": cached, "saved": saved, "when": when})


class RollupTests(unittest.TestCase):
    """Daily rollups: exactly-once aggregation of yesterday's events into dashboards."""

    def setUp(self):
        self.engine = create_engine("sqlite://")
        with self.engine.begin() as conn:
            conn.execute(text(USAGE_DDL))
            conn.execute(text(ROLLUP_DDL))
            conn.execute(text(STATE_DDL))
        self.session = Session(self.engine)
        self.now = datetime.now(UTC)
        self.tenant = "ws_" + self.id().rsplit(".", 1)[-1]  # unique per test (rollup throttle)
        repositories._rollup_last_run.clear()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.session.close)

    def test_rollup_moves_yesterdays_events_exactly_once(self):
        yesterday = self.now - timedelta(days=1)
        _insert_event(self.session, self.tenant, 1, 0.02, yesterday)
        _insert_event(self.session, self.tenant, 0, 0.0, yesterday, provider="premium")
        _insert_event(self.session, self.tenant, 0, 0.0, self.now)  # today's event stays live
        self.session.commit()

        result = rollup_daily(self.session, self.tenant)
        self.assertEqual(result["events_rolled"], 2)
        rows = self.session.execute(text(
            "SELECT provider, requests, cache_hits, saved FROM daily_usage_rollups "
            "WHERE tenant_id=:t ORDER BY provider"), {"t": self.tenant}).all()
        self.assertEqual(len(rows), 2)
        by_provider = {row[0]: row for row in rows}
        self.assertEqual(by_provider["mock"][1], 1)
        self.assertEqual(by_provider["mock"][2], 1)  # the cached hit
        self.assertEqual(by_provider["premium"][1], 1)

        cutoff = self.now.replace(hour=0, minute=0, second=0, microsecond=0)
        watermark = self.session.execute(text(
            "SELECT last_event_id FROM usage_rollup_state WHERE tenant_id=:t"), {"t": self.tenant}).scalar()
        max_id = self.session.execute(text(
            "SELECT max(id) FROM usage_events WHERE created_at < :cutoff"), {"cutoff": cutoff}).scalar()
        self.assertEqual(watermark, max_id)

        again = rollup_daily(self.session, self.tenant)
        self.assertEqual(again["events_rolled"], 0)  # idempotent: watermark prevents double counting

    def test_totals_combines_rollups_with_today_events(self):
        yesterday = self.now - timedelta(days=1)
        _insert_event(self.session, self.tenant, 1, 0.02, yesterday)
        _insert_event(self.session, self.tenant, 0, 0.0, self.now)
        self.session.commit()

        totals = UsageRepository(self.session).totals(self.tenant)
        self.assertEqual(totals["requests"], 2)
        self.assertEqual(totals["cache_hits"], 1)
        self.assertEqual({d["date"] for d in totals["by_day"]},
                         {str(yesterday.date()), str(self.now.date())})
        self.assertAlmostEqual(sum(d["saved"] for d in totals["by_day"]), 0.02, places=6)

    def test_maybe_rollup_never_raises_on_missing_tables(self):
        engine = create_engine("sqlite://")  # no tables at all
        session = Session(engine)
        try:
            repositories.maybe_rollup(session, self.tenant, min_interval_seconds=0)
            self.assertTrue(True)
        finally:
            session.close()
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
