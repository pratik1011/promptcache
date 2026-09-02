"""Streaming (SSE) tests: mock-provider format, demo + production accounting."""
import json
import tempfile
import unittest
from types import SimpleNamespace

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from promptcache.core.gateway import stream_complete
from promptcache.db.store import Store
from promptcache.production.gateway import stream_complete as production_stream_complete
from promptcache.providers.adapters import stream_provider

PROVIDER = {"id": "demo", "type": "generic", "baseUrl": "mock://local", "model": "demo",
            "inputCostPerMillion": 1, "outputCostPerMillion": 2}
SETTINGS = SimpleNamespace(providers=[PROVIDER], routes=[{"maxComplexity": 10, "provider": "demo"}],
                           similarity_threshold=0.92, cache_ttl_seconds=86400, port=0,
                           api_key="x", data_file="")
BODY = {"messages": [{"role": "user", "content": "Summarize the refund policy"}], "stream": True}


class AdapterStreamTests(unittest.TestCase):
    def test_mock_stream_is_valid_sse(self):
        chunks = list(stream_provider(PROVIDER, BODY))
        self.assertTrue(chunks)
        for chunk in chunks:
            self.assertTrue(chunk.startswith("data: "), chunk)
            self.assertTrue(chunk.endswith("\n\n"), chunk)
        self.assertEqual(chunks[-1], "data: [DONE]\n\n")
        text = ""
        for chunk in chunks[:-1]:
            payload = json.loads(chunk[6:])
            text += payload["choices"][0]["delta"].get("content", "")
        self.assertIn("Summarize", text)


class DemoStreamTests(unittest.TestCase):
    def test_stream_complete_records_usage_and_bypasses_cache(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(d + "/db.json")
            chunks = list(stream_complete(BODY, SETTINGS, store))
            self.assertEqual(chunks[-1], "data: [DONE]\n\n")
            self.assertEqual(store.state["cache"], [])  # streaming bypasses the cache
            self.assertEqual(len(store.state["events"]), 1)
            event = store.state["events"][0]
            self.assertFalse(event["cached"])
            self.assertGreater(event["baselineCost"], 0)
            self.assertGreaterEqual(event["saved"], 0)
            self.assertGreaterEqual(event["latencyMs"], 0)

    def test_stream_complete_validates_messages(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(d + "/db.json")
            with self.assertRaises(ValueError):
                list(stream_complete({"messages": [], "stream": True}, SETTINGS, store))


class ProductionStreamTests(unittest.TestCase):
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

    def test_stream_complete_records_usage(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        with engine.begin() as conn:
            conn.execute(text(self.USAGE_DDL))
        with Session(engine) as session:
            chunks = list(production_stream_complete(BODY, "t_stream", SETTINGS, session))
            self.assertEqual(chunks[-1], "data: [DONE]\n\n")
            row = session.execute(text(
                "SELECT tenant_id, provider, cached, baseline_cost FROM usage_events")).first()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "t_stream")
            self.assertEqual(row[1], "demo")
            self.assertFalse(row[2])
            self.assertGreater(row[3], 0)


if __name__ == "__main__":
    unittest.main()
