"""Gateway resilience: embedding outages, retry backoff, and circuit breakers."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from promptcache.production import gateway as gateway_module
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


FAKE_RESPONSE = {
    "id": "chatcmpl-test", "object": "chat.completion", "model": "cheap",
    "choices": [{"message": {"role": "assistant", "content": "Retry worked."}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
}


class RetryAndCircuitTests(unittest.TestCase):
    """Breaker + exponential backoff behavior through the production gateway."""

    def setUp(self):
        self.engine = create_engine("sqlite://")
        with self.engine.begin() as conn:
            conn.execute(text(USAGE_DDL))
        self.session = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.session.close)
        gateway_module.breaker.reset()

    def _patches(self):
        return [
            patch.object(gateway_module, "_get_embedder", return_value=None),
            patch.object(gateway_module, "CacheRepository", SilentCache),
        ]

    def test_retries_then_succeeds_with_backoff(self):
        with patch.object(gateway_module, "call_provider", side_effect=[RuntimeError("down"), FAKE_RESPONSE]) as call, \
             patch.object(gateway_module, "sleep") as sleeper, \
             patch.object(gateway_module, "_get_embedder", return_value=None), \
             patch.object(gateway_module, "CacheRepository", SilentCache):
            result = complete({"messages": [{"role": "user", "content": "please retry this"}]},
                              "ws_retry", SETTINGS, self.session)
        self.assertEqual(call.call_count, 2)
        sleeper.assert_called_once_with(0.5)  # next_delay(0)
        self.assertFalse(result["promptcache"]["cached"])
        self.assertEqual(result["promptcache"]["provider"], "cheap")

    def test_circuit_open_skips_hosed_provider(self):
        gateway_module.breaker.fail_threshold = 2
        request = {"messages": [{"role": "user", "content": "keep failing"}]}
        with patch.object(gateway_module, "call_provider", side_effect=RuntimeError("down")) as call, \
             patch.object(gateway_module, "sleep") as sleeper, \
             patch.object(gateway_module, "_get_embedder", return_value=None), \
             patch.object(gateway_module, "CacheRepository", SilentCache):
            with self.assertRaises(RuntimeError):
                complete(request, "ws_circuit", SETTINGS, self.session)
            self.assertEqual(call.call_count, 2)  # max_retries=1 -> 2 attempts, then circuit opened
            with self.assertRaises(RuntimeError):
                complete(request, "ws_circuit", SETTINGS, self.session)
            self.assertEqual(call.call_count, 2)  # no new upstream attempts while open
        self.assertGreaterEqual(sleeper.call_count, 1)

    def test_success_flips_circuit_back_closed(self):
        gateway_module.breaker.fail_threshold = 2
        request = {"messages": [{"role": "user", "content": "flaky but recoverable"}]}
        with patch.object(gateway_module, "call_provider", return_value=FAKE_RESPONSE) as call, \
             patch.object(gateway_module, "_get_embedder", return_value=None), \
             patch.object(gateway_module, "CacheRepository", SilentCache):
            # one failure via record_failure to mirror a prior outage, then success resets it
            gateway_module.breaker.record_failure("cheap")
            result = complete(request, "ws_recover", SETTINGS, self.session)
        self.assertEqual(call.call_count, 1)
        self.assertFalse(result["promptcache"]["cached"])
        self.assertTrue(gateway_module.breaker.allow("cheap"))


if __name__ == "__main__":
    unittest.main()
