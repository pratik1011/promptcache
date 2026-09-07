'''Write-behind semantic cache enrichment that never blocks gateway responses.'''
from concurrent.futures import ThreadPoolExecutor
import logging
from sqlalchemy.orm import Session

from ..core.scope import resolve_semantic_scope
from ..providers.embeddings import build_embedding_provider
from .db import CacheRecord, SessionLocal


logger = logging.getLogger('promptcache.scope_jobs')
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='scope-enricher')
_embedder = None
_embedder_loaded = False


def enqueue_scope_enrichment(record_id: int, prompt: str) -> None:
    _executor.submit(_enrich, record_id, prompt)


def _embedding_provider():
    global _embedder, _embedder_loaded
    if not _embedder_loaded:
        _embedder_loaded = True
        _embedder = build_embedding_provider()
    return _embedder


def _enrich(record_id: int, prompt: str) -> None:
    try:
        scope = resolve_semantic_scope([{'role': 'user', 'content': prompt}], allow_model=True)
        if not scope.enabled:
            return
        embedder = _embedding_provider()
        if embedder is None:
            return
        vector = embedder.embed(prompt)
        with SessionLocal() as session:
            record = session.get(CacheRecord, record_id)
            if record is None or record.semantic_scope != 'exact-only':
                return
            record.semantic_scope = scope.fingerprint
            record.embedding = vector
            session.commit()
    except Exception:
        logger.exception('background semantic scope enrichment failed for cache record %s', record_id)
