"""Embedding providers used by semantic cache implementations."""
import hashlib
import json
import math
import logging
import os
import urllib.request
from typing import Protocol

logger = logging.getLogger("promptcache")

class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]: ...

class DeterministicEmbedding:
    """Dependency-free fallback for local evaluation; not a semantic model."""
    def __init__(self, dimensions: int = 64):
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[index] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

class OpenAICompatibleEmbedding:
    def __init__(self, endpoint: str, api_key: str, model: str = "text-embedding-3-small", dimensions: int | None = None):
        self.endpoint, self.api_key, self.model, self.dimensions = endpoint, api_key, model, dimensions

    def embed(self, text: str) -> list[float]:
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps({"model": self.model, "input": text, **({"dimensions": self.dimensions} if self.dimensions else {})}).encode(),
            headers={"content-type": "application/json", "authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read())
        return payload["data"][0]["embedding"]

class FastEmbedEmbedding:
    """Free local semantic embedding provider backed by BGE-small."""
    def __init__(self, model: str = "BAAI/bge-small-en-v1.5"):
        from fastembed import TextEmbedding
        self.model = TextEmbedding(model_name=model)
    def embed(self, text: str) -> list[float]:
        return list(next(self.model.embed([text])))

def build_embedding_provider():
    """Select the semantic embedding provider from environment configuration.

    EMBEDDING_PROVIDER: fastembed (default), openai-compatible, deterministic, none
    EMBEDDING_MODEL / EMBEDDING_ENDPOINT / EMBEDDING_API_KEY configure the remote provider.
    Every provider emits 384-dimension vectors to match the cache_records.embedding
    vector(384) column in schema.sql. Returns None when embeddings are disabled by
    config or unavailable, which makes the gateway fail open on exact-cache lookups.
    """
    kind = os.getenv("EMBEDDING_PROVIDER", "fastembed").strip().lower() or "fastembed"
    if kind in ("none", "disabled", "off", "0", "false"):
        return None
    if kind == "deterministic":
        return DeterministicEmbedding(dimensions=384)
    if kind == "openai-compatible":
        endpoint = os.getenv("EMBEDDING_ENDPOINT", "").strip()
        api_key = os.getenv("EMBEDDING_API_KEY", "").strip()
        if not endpoint or not api_key:
            logger.warning("EMBEDDING_PROVIDER=openai-compatible requires EMBEDDING_ENDPOINT and EMBEDDING_API_KEY; semantic cache disabled")
            return None
        return OpenAICompatibleEmbedding(endpoint=endpoint, api_key=api_key,
                                         model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
                                         dimensions=384)
    # fastembed (default): local ONNX model, no API key required.
    try:
        return FastEmbedEmbedding(model=os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"))
    except Exception as exc:
        logger.warning("fastembed unavailable (%s); semantic cache disabled", exc)
        return None
