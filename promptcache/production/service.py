"""Production service seam for cache, routing, providers, and usage persistence."""
from dataclasses import dataclass
from typing import Any
from .repositories import CacheRepository, UsageRepository

@dataclass
class ProductionService:
    cache: CacheRepository
    usage: UsageRepository
    provider_registry: Any
    embedding_provider: Any | None = None
    hot_cache: Any | None = None

    def semantic_lookup(self, tenant_id: str, vector: list[float], limit: int = 1) -> list[dict[str, Any]]:
        """Delegate vector lookup to the configured repository."""
        if self.embedding_provider is None:
            return []
        return [
            {"prompt": record.prompt, "provider": record.provider, "similarity": float(score)}
            for record, score in self.cache.semantic(tenant_id, vector, limit=limit)
        ]

    def record_usage(self, **event: Any) -> None:
        self.usage.record(**event)


    def complete(self, tenant_id: str, request: dict[str, Any], fallback_gateway=None) -> dict[str, Any]:
        """Compose production dependencies; fallback_gateway supports local migration."""
        if fallback_gateway is None:
            raise RuntimeError("A provider registry and production cache gateway are required")
        result = fallback_gateway(request)
        result.setdefault("promptcache", {})["tenant"] = tenant_id
        return result
