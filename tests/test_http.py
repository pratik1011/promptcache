"""HTTP-level tests for the FastAPI production app (TestClient over SQLite).

The app normally talks to Postgres/Redis; here we patch its session factory to
an in-memory SQLite schema and its startup hooks, then exercise the public
routes end to end: signup, login, workspace creation (including the 402 plan
limit), gateway completion against the mock provider, and metrics.
"""
import json
import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

# The app reads settings at import time; force a deterministic mock environment
# regardless of any local .env file before importing the module.
os.environ["APP_ENV"] = "development"
os.environ["ADMIN_API_KEY"] = "http-test-admin-key"
os.environ["PROVIDERS_JSON"] = json.dumps(
    [{"id": "demo", "type": "generic", "baseUrl": "mock://local", "model": "demo",
      "inputCostPerMillion": 1, "outputCostPerMillion": 2}])
os.environ["ROUTES_JSON"] = json.dumps([{"maxComplexity": 10, "provider": "demo"}])

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from promptcache.production import app as app_module  # noqa: E402

DDL = """
CREATE TABLE users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  plan TEXT NOT NULL DEFAULT 'developer',
  subscription_status TEXT NOT NULL DEFAULT 'free',
  stripe_customer_id TEXT,
  stripe_subscription_id TEXT,
  current_period_end TIMESTAMP,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE workspaces (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_id INTEGER,
  name TEXT NOT NULL,
  tenant_id TEXT NOT NULL UNIQUE,
  baseline_provider TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  monthly_budget NUMERIC NOT NULL DEFAULT 100,
  rate_limit_per_minute INTEGER NOT NULL DEFAULT 60,
  max_retries INTEGER NOT NULL DEFAULT 1,
  timeout_seconds INTEGER NOT NULL DEFAULT 30,
  alerts_enabled BOOLEAN NOT NULL DEFAULT 1,
  budget_alert_percent INTEGER NOT NULL DEFAULT 80,
  latency_alert_ms INTEGER NOT NULL DEFAULT 5000,
  cache_hit_alert_percent INTEGER NOT NULL DEFAULT 20,
  webhook_url_encrypted TEXT
);
CREATE TABLE api_keys (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id TEXT NOT NULL,
  key_hash TEXT NOT NULL UNIQUE,
  active BOOLEAN NOT NULL DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMP,
  last_rotated_at TIMESTAMP,
  key_encrypted TEXT,
  last_revealed_at TIMESTAMP
);
CREATE TABLE usage_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  cached BOOLEAN NOT NULL,
  actual_cost NUMERIC NOT NULL,
  baseline_cost NUMERIC NOT NULL,
  saved NUMERIC NOT NULL,
  latency_ms INTEGER NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
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
);
CREATE TABLE workspace_providers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id TEXT NOT NULL,
  provider_type TEXT NOT NULL,
  name TEXT NOT NULL,
  base_url TEXT NOT NULL,
  model TEXT NOT NULL,
  api_key_encrypted TEXT NOT NULL,
  input_cost_per_million NUMERIC NOT NULL DEFAULT 0,
  output_cost_per_million NUMERIC NOT NULL DEFAULT 0,
  active BOOLEAN NOT NULL DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  message TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'info',
  read_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class AppHttpTests(unittest.TestCase):
    def setUp(self):
        # One shared in-memory SQLite connection: TestClient serves requests on a
        # different thread, and sqlite:// would otherwise give each thread its own
        # empty database.
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        with self.engine.begin() as conn:
            for statement in DDL.split(";"):
                statement = statement.strip()
                if statement:
                    conn.execute(text(statement))
        self.sessionmaker = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.addCleanup(self.engine.dispose)

    @contextmanager
    def _patched_client(self):
        """Serve the app with the SQLite session factory and no-op startup hooks."""
        with patch.object(app_module, "SessionLocal", self.sessionmaker), \
                patch.object(app_module, "initialize_database", lambda *a, **k: None), \
                patch.object(app_module, "bootstrap", lambda *a, **k: None), \
                patch.object(app_module, "prune_expired", lambda *a, **k: None), \
                TestClient(app_module.app) as client:
            yield client

    def test_health(self):
        with self._patched_client() as client:
            response = client.get("/health")
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["providers"][0]["id"], "demo")

    def test_signup_login_workspace_completion_metrics(self):
        with self._patched_client() as client:
            response = client.post("/v1/auth/signup",
                                   json={"email": "dev@example.com", "password": "long-enough-password"})
            self.assertEqual(response.status_code, 201)
            token = response.json()["access_token"]
            response = client.post("/v1/auth/signup",
                                   json={"email": "dev@example.com", "password": "long-enough-password"})
            self.assertEqual(response.status_code, 400)
            response = client.post("/v1/auth/login",
                                   json={"email": "dev@example.com", "password": "long-enough-password"})
            self.assertEqual(response.status_code, 200)
            response = client.post("/v1/workspaces", json={"name": "Acme"},
                                   headers={"Authorization": f"Bearer {token}"})
            self.assertEqual(response.status_code, 200)
            api_key = response.json()["api_key"]
            self.assertTrue(api_key.startswith("pc_"))
            response = client.post("/v1/workspaces", json={"name": "Second"},
                                   headers={"Authorization": f"Bearer {token}"})
            self.assertEqual(response.status_code, 402)
            self.assertIn("Developer", response.json()["detail"])
            response = client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["workspaces"][0]["name"], "Acme")
            response = client.post("/v1/chat/completions",
                                   json={"messages": [{"role": "user", "content": "Summarize refunds"}],
                                         "cache": False},
                                   headers={"Authorization": f"Bearer {api_key}"})
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertFalse(body["promptcache"]["cached"])
            self.assertEqual(body["promptcache"]["provider"], "demo")
            response = client.get("/v1/metrics", headers={"Authorization": f"Bearer {api_key}"})
            self.assertEqual(response.status_code, 200)
            self.assertGreaterEqual(response.json()["requests"], 1)

    def test_metrics_rejects_bad_key(self):
        with self._patched_client() as client:
            response = client.get("/v1/metrics", headers={"Authorization": "Bearer pc_nope"})
            self.assertEqual(response.status_code, 401)

    def test_completions_requires_auth(self):
        with self._patched_client() as client:
            response = client.post("/v1/chat/completions",
                                   json={"messages": [{"role": "user", "content": "hi"}]})
            self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()