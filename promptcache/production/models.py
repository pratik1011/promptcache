from dataclasses import dataclass
from datetime import datetime
from typing import Any

@dataclass
class CacheRecord:
    tenant_id: str
    cache_key: str
    prompt: str
    response: dict[str, Any]
    embedding: list[float]
    provider: str
    cost: float
    created_at: datetime
    expires_at: datetime

@dataclass
class UsageEvent:
    tenant_id: str
    provider: str
    cached: bool
    actual_cost: float
    baseline_cost: float
    saved: float
    latency_ms: int
    created_at: datetime
