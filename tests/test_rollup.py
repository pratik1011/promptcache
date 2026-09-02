"""Daily usage rollup: incremental aggregation, idempotence, and fast totals."""
import unittest
from datetime import datetime, timedelta, UTC

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from promptcache.production.repositories import maybe_rollup, rollup_daily
from promptcache.production.repositories import UsageRepository

DDL = [
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
    """
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
)""",
    """
CREATE TABLE usage_rollup_state (
  tenant_id TEXT PRIMARY KEY,
  last_event_id INTEGER NOT NULL DEFAULT 0
)""",
]


def _register_adapter():
    import sqlite3
    sqlite3.register_adapter(datetime, lambda value: value.isoformat(sep=" "))


_register_adapter()


class RollupTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        with self.engine.begin() as conn:
            for statement in DDL:
                conn.execute(text(statement))
        self.session = Session(self.engine)
        self.addCleanup(self.session.close)
        self.now = datetime.now(UTC)
        self.yesterday = self.now - timedelta(days=1)
        self.two_days_ago = self.now - timedelta(days=2)
        rows = [
            # (provider, cached, actual, baseline, saved, created_at)
            ("cheap", True, 0.0, 0.02, 0.02, self.two_days_ago),
            ("cheap", False, 0.01, 0.02, 0.01, self.two_days_ago),
            ("premium", False, 0.03, 0.03, 0.0, self.yesterday),
            ("cheap", True, 0.0, 0.02, 0.02, self.yesterday),
            ("cheap", False, 0.005, 0.02, 0.015, self.now),  # today: stays live
        ]
        with self.engine.begin() as conn:
            for provider, cached, actual, baseline, saved, created in rows:
                conn.execute(text(
                    "INSERT INTO usage_events (tenant_id, provider, cached, actual_cost,"
                    " baseline_cost, saved, latency_ms, created_at)"
                    " VALUES ('t1', :p, :c, :a, :b, :s, 5, :ts)"),
                    {"p": provider, "c": cached, "a": actual, "b": baseline, "s": saved,
                     "ts": created.isoformat(sep=" ")})

    def test_rollup_excludes_today_and_aggregates(self):
        result = rollup_daily(self.session, "t1")
        self.assertEqual(result["events_rolled"], 4)  # today's event not rolled
        rows = self.session.execute(text(
            "SELECT day, provider, requests, cache_hits, actual_cost, saved"
            " FROM daily_usage_rollups ORDER BY day, provider")).all()
        self.assertEqual(len(rows), 3)
        day2 = self.two_days_ago.date().isoformat()
        day1 = self.yesterday.date().isoformat()
        self.assertEqual((rows[0][0], rows[0][1], rows[0][2], rows[0][3]), (day2, "cheap", 2, 1))
        self.assertAlmostEqual(float(rows[0][4]), 0.01)
        self.assertEqual((rows[1][0], rows[1][1], rows[1][2], rows[1][3]), (day1, "cheap", 1, 1))
        self.assertEqual((rows[2][0], rows[2][1]), (day1, "premium"))
        watermark = self.session.execute(text(
            "SELECT last_event_id FROM usage_rollup_state WHERE tenant_id='t1'")).scalar()
        self.assertEqual(watermark, 4)  # id of the last pre-today event

    def test_rollup_is_idempotent(self):
        rollup_daily(self.session, "t1")
        first = self.session.execute(text(
            "SELECT requests, saved FROM daily_usage_rollups"
            " WHERE provider='cheap' ORDER BY day")).all()
        rollup_daily(self.session, "t1")  # second pass must not double-count
        second = self.session.execute(text(
            "SELECT requests, saved FROM daily_usage_rollups"
            " WHERE provider='cheap' ORDER BY day")).all()
        self.assertEqual([(r[0], float(r[1])) for r in first], [(r[0], float(r[1])) for r in second])

    def test_totals_combine_rollup_and_live(self):
        rollup_daily(self.session, "t1")
        totals = UsageRepository(self.session).totals("t1")
        self.assertEqual(totals["requests"], 5)
        self.assertEqual(totals["cache_hits"], 2)  # one hit on each pre-today day
        self.assertAlmostEqual(totals["saved"], 0.065)
        days = {entry["date"]: entry for entry in totals["by_day"]}
        self.assertEqual(days[self.two_days_ago.date().isoformat()]["requests"], 2)
        self.assertEqual(days[self.now.date().isoformat()]["requests"], 1)  # today is live
        providers = {entry["provider"]: entry for entry in totals["by_provider"]}
        self.assertEqual(providers["cheap"]["requests"], 4)

    def test_maybe_rollup_never_raises(self):
        self.session.execute(text("DROP TABLE daily_usage_rollups"))
        self.session.commit()
        maybe_rollup(self.session, "t1", min_interval_seconds=0)  # must not raise
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
