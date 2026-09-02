"""Smoke tests for the zero-dependency demo HTTP server.

These exist because the auth helpers and the GET/POST handlers were once
accidentally indented inside do_OPTIONS, leaving the server unable to
answer any request. If Handler loses do_GET/do_POST again, these fail.
"""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from promptcache.api import server as demo
from promptcache.config.settings import Settings
from promptcache.db.store import Store

PROVIDER = {"id": "demo", "type": "generic", "baseUrl": "mock://local", "model": "demo",
            "inputCostPerMillion": 1, "outputCostPerMillion": 2}


class DemoServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls._orig_settings, cls._orig_store = demo.settings, demo.store
        demo.settings = Settings(0, "test-admin-key", .92, 86400, [PROVIDER],
                                 [{"maxComplexity": 10, "provider": "demo"}],
                                 cls._tmp.name + "/db.json")
        demo.store = Store(demo.settings.data_file)
        demo._USERS.clear()
        demo._TENANTS.clear()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), demo.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.thread.join(timeout=5)
        cls.httpd.server_close()
        demo.settings, demo.store = cls._orig_settings, cls._orig_store
        cls._tmp.cleanup()

    def request(self, method, path, payload=None, auth=None):
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = auth
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.httpd.server_address[1]}{path}",
            data=json.dumps(payload).encode() if payload is not None else None,
            headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as err:
            raw = err.read()
            err.close()
            return err.code, raw

    def json_request(self, method, path, payload=None, auth=None):
        status, raw = self.request(method, path, payload, auth)
        return status, json.loads(raw) if raw else None

    def test_health_lists_providers(self):
        status, body = self.json_request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["providers"][0]["id"], "demo")

    def test_root_serves_html(self):
        status, raw = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"<html", raw[:200].lower())

    def test_options_preflight(self):
        status, _ = self.request("OPTIONS", "/v1/chat/completions")
        self.assertEqual(status, 204)

    def test_signup_login_and_me(self):
        payload = {"email": "dev@example.com", "password": "long-enough-password", "workspace_name": "Acme"}
        status, body = self.json_request("POST", "/v1/auth/signup", payload)
        self.assertEqual(status, 201)
        self.assertTrue(body["api_key"].startswith("pc_"))
        status, _ = self.json_request("POST", "/v1/auth/signup", payload)
        self.assertEqual(status, 409)
        status, body = self.json_request("POST", "/v1/auth/login",
                                         {"email": "dev@example.com", "password": "long-enough-password"})
        self.assertEqual(status, 200)
        status, body = self.json_request("GET", "/v1/me", auth=f"Bearer {body['access_token']}")
        self.assertEqual(status, 200)
        self.assertEqual(body["workspaces"][0]["name"], "Acme")

    def test_chat_and_metrics_require_auth_and_work(self):
        status, _ = self.json_request("POST", "/v1/chat/completions",
                                      {"messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(status, 401)
        status, _ = self.json_request("GET", "/v1/metrics")
        self.assertEqual(status, 401)
        status, body = self.json_request("POST", "/v1/chat/completions",
                                         {"messages": [{"role": "user", "content": "Summarize refunds"}]},
                                         auth="Bearer test-admin-key")
        self.assertEqual(status, 200)
        self.assertIn("promptcache", body)
        status, body = self.json_request("GET", "/v1/metrics", auth="Bearer test-admin-key")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(body["requests"], 1)

    def test_streaming_sse(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.httpd.server_address[1]}/v1/chat/completions",
            data=json.dumps({"messages": [{"role": "user", "content": "hello streaming world"}],
                             "stream": True}).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer test-admin-key"},
            method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            self.assertEqual(resp.status, 200)
            self.assertTrue(resp.headers.get("Content-Type", "").startswith("text/event-stream"))
            body = resp.read().decode("utf-8")
        self.assertIn("data: [DONE]", body)
        self.assertIn("hello", body)
        status, metrics = self.json_request("GET", "/v1/metrics", auth="Bearer test-admin-key")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(metrics["requests"], 1)


if __name__ == "__main__":
    unittest.main()
