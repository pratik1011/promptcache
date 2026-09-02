"""Production auth + baseline-provider tests (SQLite-backed; no live Postgres needed)."""
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from promptcache.production import auth
from promptcache.production.gateway import _baseline_provider

# Python 3.12+ deprecated the default datetime adapters; register our own so
# tz-aware datetimes survive a SQLite round-trip as ISO strings.
sqlite3.register_adapter(datetime, lambda value: value.isoformat(sep=" "))

API_KEYS_DDL = """
CREATE TABLE api_keys (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id TEXT NOT NULL,
  key_hash TEXT NOT NULL UNIQUE,
  active BOOLEAN NOT NULL DEFAULT 1,
  created_at TIMESTAMP,
  expires_at TIMESTAMP,
  last_rotated_at TIMESTAMP,
  key_encrypted TEXT,
  last_revealed_at TIMESTAMP
)
"""

WORKSPACES_DDL = """
CREATE TABLE workspaces (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_id INTEGER,
  name TEXT,
  tenant_id TEXT,
  baseline_provider TEXT
)
"""

PROVIDERS = [
    {"id": "cheap", "inputCostPerMillion": 1, "outputCostPerMillion": 2},
    {"id": "premium", "inputCostPerMillion": 10, "outputCostPerMillion": 20},
]


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        with self.engine.begin() as conn:
            conn.execute(text(API_KEYS_DDL))
        self.session = Session(self.engine)

    def tearDown(self):
        self.session.close()

    def test_key_hash_is_fast_sha256_format(self):
        self.assertTrue(auth.key_hash("pc_whatever").startswith("sha256:"))

    def test_create_and_authenticate(self):
        raw, expires = auth.create_key(self.session, "t_ws1")
        self.assertTrue(raw.startswith("pc_"))
        self.assertIsNotNone(expires)
        self.assertEqual(auth.authenticate(self.session, raw), "t_ws1")
        self.assertIsNone(auth.authenticate(self.session, "pc_not-the-key"))

    def test_expired_key_rejected(self):
        raw, _ = auth.create_key(self.session, "t_ws2")
        self.session.execute(text("UPDATE api_keys SET expires_at=:e"),
                             {"e": datetime.now(timezone.utc) - timedelta(days=1)})
        self.session.commit()
        self.assertIsNone(auth.authenticate(self.session, raw))

    def test_revoked_key_rejected(self):
        raw, _ = auth.create_key(self.session, "t_ws3")
        auth.revoke_all_keys(self.session, "t_ws3")
        self.assertIsNone(auth.authenticate(self.session, raw))

    def test_legacy_scrypt_keys_still_authenticate(self):
        raw = "pc_legacy-key-value"
        self.session.execute(text("INSERT INTO api_keys (tenant_id, key_hash, active) VALUES (:t, :h, 1)"),
                             {"t": "t_old", "h": auth._legacy_scrypt_hash(raw)})
        self.session.commit()
        self.assertEqual(auth.authenticate(self.session, raw), "t_old")


class BaselineProviderTests(unittest.TestCase):
    def setUp(self):
        self.settings = SimpleNamespace(providers=PROVIDERS)

    def _session(self, with_table):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        if with_table:
            with engine.begin() as conn:
                conn.execute(text(WORKSPACES_DDL))
        return Session(engine)

    def test_falls_back_to_most_expensive_provider(self):
        with self._session(with_table=True) as session:
            session.execute(text("INSERT INTO workspaces (tenant_id, owner_id, name) VALUES ('t_a', 1, 'A')"))
            session.commit()
            self.assertEqual(_baseline_provider(self.settings, session, "t_a")["id"], "premium")

    def test_prefers_workspace_baseline(self):
        with self._session(with_table=True) as session:
            session.execute(text("INSERT INTO workspaces (tenant_id, owner_id, name, baseline_provider) VALUES ('t_b', 1, 'B', 'cheap')"))
            session.commit()
            self.assertEqual(_baseline_provider(self.settings, session, "t_b")["id"], "cheap")

    def test_unknown_baseline_falls_back(self):
        with self._session(with_table=True) as session:
            session.execute(text("INSERT INTO workspaces (tenant_id, owner_id, name, baseline_provider) VALUES ('t_c', 1, 'C', 'ghost')"))
            session.commit()
            self.assertEqual(_baseline_provider(self.settings, session, "t_c")["id"], "premium")

    def test_missing_table_falls_back(self):
        with self._session(with_table=False) as session:
            self.assertEqual(_baseline_provider(self.settings, session, "t_x")["id"], "premium")


if __name__ == "__main__":
    unittest.main()
