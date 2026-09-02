"""Gateway resilience: an embedding outage must never break gateway requests."""
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from promptcache.production.gateway import complete

PROVIDER = {"id": "cheap", "type": "generic", "baseUrl": "mock://local", "model": "cheap",
            "inputCostPerMillion": 1, "outputCostPerMillion": 2}
SETTINGS = SimpleNamespace(providers=[PROVIDER],
                           routes=[{"maxComplexity": 10, "provider": "cheap"}],
                           similarity_threshold=0.92, cache_ttl_seconds=86400,
                           max_retries=1, timeout_seconds=30)

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
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""


class FailingEmbedder:
    def embed(self, text):
        raise RuntimeError("embedding provider is down")


class SilentCache:
    """CacheRepository stand-in: no exact hits, no persistence, raises on vector lookup."""

    def __init__(self, session):
        self.session = session

    def exact(self, tenant_id, cache_key):
        return None

    def semantic(self, tenant_id, vector, limit=5):
        raise RuntimeError("vector index unavailable")

    def save(self, **values):
        return None


class GatewayFailOpenTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        with self.engine.begin() as conn:
            conn.execute(text(USAGE_DDL))
        self.session = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.session.close)

    def test_embedding_failure_degrades_to_passthrough(self):
        request = {"messages": [{"role": "user", "content": "what is the refund policy"}]}
        with patch("promptcache.production.gateway.CacheRepository", SilentCache), \
             patch("promptcache.production.gateway._get_embedder", return_value=FailingEmbedder()):
            result = complete(request, "ws_failopen", SETTINGS, self.session)
        self.assertFalse(result["promptcache"]["cached"])
        self.assertEqual(result["promptcache"]["provider"], "cheap")
        # usage was still recorded despite the embedding outage
        rows = self.session.execute(text("SELECT count(*) FROM usage_events")).scalar()
        self.assertEqual(rows, 1)

    def test_semantic_lookup_skipped_when_embeddings_disabled(self):
        class RecordingCache(SilentCache):
            semantic_calls = 0

            def semantic(self, tenant_id, vector, limit=5):
                RecordingCache.semantic_calls += 1
                raise AssertionError("semantic lookup must not run without an embedder")

        with patch("promptcache.production.gateway.CacheRepository", RecordingCache), \
             patch("promptcache.production.gateway._get_embedder", return_value=None):
            complete({"messages": [{"role": "user", "content": "hello world"}]},
                     "ws_disabled", SETTINGS, self.session)
        self.assertEqual(RecordingCache.semantic_calls, 0)

    def test_request_still_succeeds_without_cache_table(self):
        request = {"messages": [{"role": "user", "content": "summarize quarterly results"}]}
        with patch("promptcache.production.gateway.CacheRepository", SilentCache), \
             patch("promptcache.production.gateway._get_embedder",
                   side_effect=RuntimeError("provider factory exploded")):
            result = complete(request, "ws_no_cache", SETTINGS, self.session)
        self.assertFalse(result["promptcache"]["cached"])
        self.assertIn("quarterly", result["choices"][0]["message"]["content"])


if __name__ == "__main__":
    unittest.main()