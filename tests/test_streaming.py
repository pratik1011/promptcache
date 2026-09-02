"""Streaming (SSE) tests: mock-provider format, demo + production accounting, cache replay."""
import json
import tempfile
import unittest
from types import SimpleNamespace

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from promptcache.core.gateway import stream_complete
from promptcache.db.store import Store
from promptcache.production.gateway import stream_complete as production_stream_complete
from promptcache.providers.adapters import cache_chunks, stream_provider
from promptcache.providers.protocol import StreamCapture

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
        content_text = ""
        for chunk in chunks[:-1]:
            payload = json.loads(chunk[6:])
            content_text += payload["choices"][0]["delta"].get("content", "")
        self.assertIn("Summarize", content_text)

    def test_cache_chunks_replays_valid_sse(self):
        response = {"id": "chatcmpl-1", "object": "chat.completion", "model": "demo",
                    "choices": [{"message": {"role": "assistant", "content": "Refund policy: 30 days."}, "finish_reason": "stop"}]}
        chunks = list(cache_chunks(response, "Refund policy: 30 days."))
        self.assertTrue(chunks)
        for chunk in chunks:
            self.assertTrue(chunk.startswith("data: "), chunk)
            self.assertTrue(chunk.endswith("\n\n"), chunk)
        self.assertEqual(chunks[-1], "data: [DONE]\n\n")
        content_text = ""
        for chunk in chunks[:-1]:
            payload = json.loads(chunk[6:])
            content_text += payload["choices"][0]["delta"].get("content", "")
        self.assertIn("Refund policy", content_text)


class DemoStreamTests(unittest.TestCase):
    def test_stream_miss_records_usage_and_caches_for_replay(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(d + "/db.json")
            first = list(stream_complete(BODY, SETTINGS, store))
            self.assertEqual(first[-1], "data: [DONE]\n\n")
            self.assertEqual(len(store.state["cache"]), 1)  # miss is now stored
            self.assertEqual(len(store.state["events"]), 1)
            self.assertFalse(store.state["events"][0]["cached"])
            self.assertGreaterEqual(store.state["events"][0]["saved"], 0)
            # identical prompt: the second stream is served from cache
            second = list(stream_complete(BODY, SETTINGS, store))
            self.assertEqual(second[-1], "data: [DONE]\n\n")
            self.assertEqual(len(store.state["cache"]), 1)  # no duplicate entries
            self.assertTrue(store.state["events"][1]["cached"])
            self.assertGreater(store.state["events"][1]["saved"], 0)
            content_text = ""
            for chunk in second[:-1]:
                payload = json.loads(chunk[6:])
                content_text += payload["choices"][0]["delta"].get("content", "")
            self.assertIn("Summarize", content_text)

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

    def setUp(self):
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        with self.engine.begin() as conn:
            conn.execute(text(self.USAGE_DDL))
            conn.execute(text(self.CACHE_DDL))
        self.session = Session(self.engine)
        self.addCleanup(self.session.close)

    def test_stream_miss_records_usage_and_caches(self):
        chunks = list(production_stream_complete(BODY, "t_stream", SETTINGS, self.session))
        self.assertEqual(chunks[-1], "data: [DONE]\n\n")
        row = self.session.execute(text(
            "SELECT tenant_id, provider, cached, baseline_cost FROM usage_events")).first()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "t_stream")
        self.assertEqual(row[1], "demo")
        self.assertFalse(row[2])
        self.assertGreater(row[3], 0)
        # the streamed response was persisted for exact-match replay
        cache_rows = self.session.execute(text("SELECT count(*), provider FROM cache_records")).first()
        self.assertEqual(cache_rows[0], 1)
        self.assertEqual(cache_rows[1], "demo")

    def test_stream_hit_replays_cached_response(self):
        # miss: streams from the provider and persists the response for replay
        first = list(production_stream_complete(BODY, "t_cached", SETTINGS, self.session))
        self.assertEqual(first[-1], "data: [DONE]\n\n")
        # hit: the identical prompt is served from the exact-match cache
        replay = list(production_stream_complete(BODY, "t_cached", SETTINGS, self.session))
        self.assertEqual(replay[-1], "data: [DONE]\n\n")

        def _content(chunks):
            out = ""
            for chunk in chunks[:-1]:
                payload = json.loads(chunk[6:])
                out += payload["choices"][0]["delta"].get("content", "")
            return out

        self.assertTrue(_content(first))
        self.assertEqual(_content(replay), _content(first))  # replayed verbatim
        rows = self.session.execute(text("SELECT cached, saved FROM usage_events ORDER BY id")).all()
        self.assertEqual(len(rows), 2)
        self.assertFalse(rows[0][0])
        self.assertTrue(rows[1][0])
        self.assertGreater(rows[1][1], 0)


def _sse(payload) -> str:
    return "data: " + json.dumps(payload) + "\n\n"


class StreamCaptureTests(unittest.TestCase):
    def test_content_and_finish_reason(self):
        capture = StreamCapture()
        capture.observe(_sse({"choices": [{"delta": {"content": "Hello "}, "finish_reason": None}]}))
        capture.observe(_sse({"choices": [{"delta": {"content": "world"}, "finish_reason": None}]}))
        capture.observe(_sse({"choices": [{"delta": {}, "finish_reason": "stop"}]}))
        message = capture.snapshot_message()
        self.assertEqual(message["content"], "Hello world")
        self.assertEqual(capture.finish_reason, "stop")
        self.assertNotIn("tool_calls", message)

    def test_usage_only_chunk_is_safe_and_captures_usage(self):
        capture = StreamCapture()
        capture.observe(_sse({"choices": [{"delta": {"content": "Hi"}, "finish_reason": None}]}))
        capture.observe(_sse({"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4}}))
        capture.observe("data: [DONE]\n\n")
        message = capture.snapshot_message()
        self.assertEqual(message["content"], "Hi")
        self.assertEqual(capture.usage, {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4})

    def test_tool_calls_merge_across_deltas(self):
        capture = StreamCapture()
        capture.observe(_sse({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_1", "type": "function",
             "function": {"name": "get_weather", "arguments": '{"city":'}}]}, "finish_reason": None}]}))
        capture.observe(_sse({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '"Paris"}'}}]}, "finish_reason": None}]}))
        capture.observe(_sse({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}))
        message = capture.snapshot_message()
        call = message["tool_calls"][0]
        self.assertEqual(call["id"], "call_1")
        self.assertEqual(call["function"]["name"], "get_weather")
        self.assertEqual(call["function"]["arguments"], '{"city":"Paris"}')
        self.assertEqual(capture.finish_reason, "tool_calls")
        self.assertIsNone(message["content"])

    def test_malformed_lines_are_ignored(self):
        capture = StreamCapture()
        capture.observe("not an sse line")
        capture.observe("data: {broken json")
        capture.observe(_sse({"choices": [{"delta": {"content": "ok"}, "finish_reason": None}]}))
        self.assertEqual(capture.snapshot_message()["content"], "ok")


class ToolCallReplayTests(unittest.TestCase):
    def test_cache_chunks_replays_tool_calls(self):
        response = {"id": "chatcmpl-2", "object": "chat.completion", "model": "demo",
                    "choices": [{"message": {"role": "assistant", "content": None,
                                             "tool_calls": [{"id": "call_1", "type": "function",
                                                             "function": {"name": "get_weather",
                                                                          "arguments": '{"city":"Paris"}'}}]},
                                 "finish_reason": "tool_calls"}]}
        chunks = list(cache_chunks(response, ""))
        self.assertEqual(chunks[-1], "data: [DONE]\n\n")
        parsed = [json.loads(c[6:]) for c in chunks if c != "data: [DONE]\n\n"]
        tool_chunks = [p for p in parsed if p["choices"][0]["delta"].get("tool_calls")]
        self.assertEqual(len(tool_chunks), 1)
        call = tool_chunks[0]["choices"][0]["delta"]["tool_calls"][0]
        self.assertEqual(call["function"]["name"], "get_weather")
        self.assertEqual(call["index"], 0)
        final = json.loads(chunks[-2][6:])
        self.assertEqual(final["choices"][0]["finish_reason"], "tool_calls")


if __name__ == "__main__":
    unittest.main()
