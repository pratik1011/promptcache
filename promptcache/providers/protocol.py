"""OpenAI wire-protocol helpers shared by the demo and production gateways.

A gateway must never (a) silently drop client parameters or (b) forward its own
control flags upstream. `upstream_body` handles both: gateway-only keys are
removed, the resolved provider always wins on `model`, and every remaining
client field (max_tokens, tools, response_format, stop, seed, n, brand-new
OpenAI params) is forwarded untouched.
"""

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
