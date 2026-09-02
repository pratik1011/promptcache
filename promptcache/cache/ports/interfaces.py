from abc import ABC, abstractmethod
from typing import Any

class EmbeddingProvider(ABC):
    """Vendor-neutral contract for converting text into vectors."""
    @abstractmethod
    def embed(self, text: str) -> list[float]:
        raise NotImplementedError

class VectorRepository(ABC):
    """Storage contract for tenant-scoped nearest-neighbor cache lookup."""
    @abstractmethod
    def upsert(self, namespace: str, key: str, vector: list[float], payload: dict[str, Any]) -> None:
        raise NotImplementedError

    @abstractmethod
    def search(self, namespace: str, vector: list[float], limit: int = 1) -> list[dict[str, Any]]:
        raise NotImplementedError
