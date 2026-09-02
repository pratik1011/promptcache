"""Structured JSON logging and X-Request-ID middleware behavior."""
import asyncio
import json
import logging
import unittest

from promptcache.production.observability import JsonFormatter, RequestIdMiddleware


def _run_asgi(middleware, scope):
    """Drive an ASGI app with a scripted exchange; returns captured messages."""
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(middleware(scope, receive, send))
    return sent


class JsonFormatterTests(unittest.TestCase):
    def _captured_record(self, **extra):
        formatter = JsonFormatter()
        logger = logging.getLogger("promptcache.test.json")
        with self.assertLogs(logger, level="INFO") as captured:
            logger.info("request %s %s", "GET", "/v1/metrics", extra=extra or None)
        return json.loads(formatter.format(captured.records[0]))

    def test_output_is_parseable_json_with_extras(self):
        payload = self._captured_record(request_id="abc123", status=200, duration_ms=12)
        self.assertEqual(payload["message"], "request GET /v1/metrics")
        self.assertEqual(payload["request_id"], "abc123")
        self.assertEqual(payload["status"], 200)
        self.assertEqual(payload["duration_ms"], 12)
        self.assertEqual(payload["level"], "INFO")

    def test_plain_records_have_no_null_extras(self):
        payload = self._captured_record()
        self.assertEqual(payload["message"], "request GET /v1/metrics")
        self.assertNotIn("request_id", payload)
        self.assertNotIn("status", payload)

    def test_exceptions_are_included(self):
        formatter = JsonFormatter()
        logger = logging.getLogger("promptcache.test.json")
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            with self.assertLogs(logger, level="ERROR") as captured:
                logger.exception("failed")
        payload = json.loads(formatter.format(captured.records[0]))
        self.assertIn("RuntimeError: boom", payload["exc_info"])


class RequestIdMiddlewareTests(unittest.TestCase):
    def _scope(self, headers=None):
        return {"type": "http", "method": "GET", "path": "/health",
                "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or [])]}

    def test_response_carries_generated_request_id(self):
        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        sent = _run_asgi(RequestIdMiddleware(app), self._scope())
        header = dict((k.decode(), v.decode()) for k, v in sent[0]["headers"])
        self.assertIn("x-request-id", header)
        self.assertEqual(sent[0]["status"], 200)

    def test_inbound_request_id_is_honored_and_sanitized(self):
        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        sent = _run_asgi(RequestIdMiddleware(app),
                         self._scope([("X-Request-ID", "trace-42\nbad")]))
        header = dict((k.decode(), v.decode()) for k, v in sent[0]["headers"])
        self.assertEqual(header["x-request-id"], "trace-42bad")

    def test_access_log_contains_request_id(self):
        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        with self.assertLogs("promptcache", level="INFO") as captured:
            _run_asgi(RequestIdMiddleware(app), self._scope())
        self.assertTrue(any(getattr(record, "request_id", None) for record in captured.records))

    def test_non_http_scopes_pass_through(self):
        async def app(scope, receive, send):
            await send({"type": "lifespan.startup.complete"})

        sent = _run_asgi(RequestIdMiddleware(app), {"type": "lifespan"})
        self.assertEqual(sent[0]["type"], "lifespan.startup.complete")


if __name__ == "__main__":
    unittest.main()
