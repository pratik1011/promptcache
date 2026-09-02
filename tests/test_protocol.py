"""OpenAI wire-protocol tests: parameter passthrough and gateway-flag stripping.

The P0 contract: a gateway must never silently drop client parameters
(max_tokens, tools, response_format, ...) and must never forward its own
control flags (cache, cache_namespace, provider) upstream.
"""
import os
import unittest

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from pydantic import ValidationError  # noqa: E402

from promptcache.providers.protocol import GATEWAY_KEYS, upstream_body  # noqa: E402


class UpstreamBodyTests(unittest.TestCase):
    def test_gateway_flags_are_stripped(self):
        body = {"messages": [{"role": "user", "content": "hi"}], "cache": True,
                "cache_namespace": "ns", "provider": "cheap", "temperature": 0.2}
        upstream = upstream_body(body, "gpt-x")
        for flag in GATEWAY_KEYS:
            self.assertNotIn(flag, upstream)
        self.assertEqual(upstream["temperature"], 0.2)

    def test_standard_params_pass_through(self):
        body = {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 256,
                "tools": [{"type": "function", "function": {"name": "f"}}],
                "tool_choice": "auto", "response_format": {"type": "json_object"},
                "stop": ["END"], "seed": 7, "n": 2, "logprobs": True}
        upstream = upstream_body(body, "m")
        for field in ("max_tokens", "tools", "tool_choice", "response_format", "stop", "seed", "n", "logprobs"):
            self.assertEqual(upstream[field], body[field])

    def test_unknown_future_params_are_not_dropped(self):
        body = {"messages": [], "brand_new_openai_param": {"a": 1}}
        upstream = upstream_body(body, "m")
        self.assertEqual(upstream["brand_new_openai_param"], {"a": 1})

    def test_provider_model_always_wins(self):
        body = {"messages": [], "model": "client-picked"}
        self.assertEqual(upstream_body(body, "provider-model")["model"], "provider-model")

    def test_stream_forced_on_streaming_path_only(self):
        body = {"messages": [], "stream": False}
        self.assertTrue(upstream_body(body, "m", stream=True)["stream"])
        self.assertFalse(upstream_body(body, "m")["stream"])  # client value preserved

    def test_input_body_not_mutated(self):
        body = {"messages": [], "cache": True, "model": "original"}
        upstream_body(body, "m", stream=True)
        self.assertEqual(body["model"], "original")
        self.assertIn("cache", body)


class CompletionRequestExtrasTests(unittest.TestCase):
    """The FastAPI request model must forward unknown fields, not drop them."""

    def test_extras_survive_model_dump(self):
        from promptcache.production.app import CompletionRequest
        request = CompletionRequest.model_validate({
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 128, "tools": [{"type": "function"}], "seed": 3,
        })
        dumped = request.model_dump()
        self.assertEqual(dumped["max_tokens"], 128)
        self.assertEqual(dumped["tools"], [{"type": "function"}])
        self.assertEqual(dumped["seed"], 3)
        self.assertEqual(dumped["cache"], True)  # defaults intact

    def test_messages_still_required(self):
        from promptcache.production.app import CompletionRequest
        with self.assertRaises(ValidationError):
            CompletionRequest.model_validate({"max_tokens": 10})

    def test_gateway_builds_clean_upstream_from_dumped_request(self):
        """End-to-end shape: what call_provider would receive for one candidate."""
        from promptcache.production.app import CompletionRequest
        request = CompletionRequest.model_validate({
            "messages": [{"role": "user", "content": "hi"}], "max_tokens": 64,
            "cache_namespace": "dash", "provider": None,
        })
        upstream = upstream_body(request.model_dump(), "gpt-4.1-mini")
        self.assertEqual(upstream["model"], "gpt-4.1-mini")
        self.assertEqual(upstream["max_tokens"], 64)
        for flag in GATEWAY_KEYS:
            self.assertNotIn(flag, upstream)


if __name__ == "__main__":
    unittest.main()
