from dataclasses import dataclass, field
from typing import Any

@dataclass
class CompletionRequest:
    messages: list[dict[str, Any]]
    provider: str | None = None
    cache: bool = True
    cache_namespace: str = "default"
    stream: bool = False

@dataclass
class ProviderConfig:
    id: str
    type: str
    base_url: str
    model: str
    api_key: str | None = None
    input_cost_per_million: float = 0
    output_cost_per_million: float = 0
    endpoint: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    response_path: str | None = None
