"""OpenAI wire-protocol helpers shared by the demo and production gateways.

A gateway must never (a) silently drop client parameters or (b) forward its own
control flags upstream. `upstream_body` handles both: gateway-only keys are
removed, the resolved provider always wins on `model`, and every remaining
client field (max_tokens, tools, response_format, stop, seed, n, brand-new
OpenAI params) is forwarded untouched.
"""
import json

# Request keys that configure PromptCache itself and must never reach a provider.
GATEWAY_KEYS = frozenset({"cache", "cache_namespace", "provider", "promptcache"})


def upstream_body(body: dict, model: str, *, stream: bool | None = None) -> dict:
    """Build the JSON body to send to the provider for one completion request.

    - `model` is forced to the provider's configured model (each failover
      candidate gets its own body, since models differ per provider);
    - `stream` is forced on the streaming path when given, otherwise the
      client's value is preserved;
    - everything else passes through unchanged.
    """
    upstream = {key: value for key, value in body.items() if key not in GATEWAY_KEYS}
    upstream["model"] = model
    if stream is not None:
        upstream["stream"] = stream
    return upstream


class StreamCapture:
    """Assembles an assistant message from streamed SSE chunks.

    Understands the full OpenAI chunk surface: `delta.content`,
    `delta.tool_calls` (merged across deltas by index, arguments
    concatenated), `finish_reason`, and the terminal usage-only chunk that
    `stream_options.include_usage` emits (`choices: []`). Malformed or
    non-data lines are ignored, so observability never breaks streaming.
    """

    def __init__(self) -> None:
        self.content_parts: list[str] = []
        self.finish_reason: str | None = None
        self.usage: dict | None = None
        self._tool_calls: dict[int, dict] = {}

    def observe(self, chunk: str) -> None:
        """Consume one yielded SSE chunk (a 'data: ...' line or [DONE])."""
        if not isinstance(chunk, str) or not chunk.startswith("data: ") or chunk == "data: [DONE]":
            return
        try:
            payload = json.loads(chunk[6:])
        except ValueError:
            return
        choices = payload.get("choices") or []
        if choices:
            choice = choices[0] or {}
            delta = choice.get("delta") or {}
            content = delta.get("content")
            if content:
                self.content_parts.append(content)
            for piece in delta.get("tool_calls") or []:
                self._merge_tool_call(piece)
            if choice.get("finish_reason") and self.finish_reason is None:
                self.finish_reason = choice["finish_reason"]
        usage = payload.get("usage")
        if isinstance(usage, dict):
            self.usage = usage

    def _merge_tool_call(self, piece: dict) -> None:
        index = piece.get("index", 0)
        entry = self._tool_calls.setdefault(index, {"id": None, "type": "function", "name": "", "arguments": []})
        if piece.get("id"):
            entry["id"] = piece["id"]
        if piece.get("type"):
            entry["type"] = piece["type"]
        function = piece.get("function") or {}
        if function.get("name"):
            entry["name"] += function["name"]
        if function.get("arguments"):
            entry["arguments"].append(function["arguments"])

    def snapshot_message(self) -> dict:
        """The assembled assistant message, OpenAI chat.completion shape."""
        message: dict = {"role": "assistant"}
        message["content"] = "".join(self.content_parts) or None
        calls = []
        for index in sorted(self._tool_calls):
            entry = self._tool_calls[index]
            calls.append({"id": entry["id"] or f"call_{index}", "type": entry["type"] or "function",
                          "function": {"name": entry["name"], "arguments": "".join(entry["arguments"]) or "{}"}})
        if calls:
            message["tool_calls"] = calls
        return message
