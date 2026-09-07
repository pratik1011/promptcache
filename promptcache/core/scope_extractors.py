'''Optional model-backed entity extraction for semantic cache scopes.'''
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
import re
import urllib.request


logger = logging.getLogger('promptcache.scope')
_local_model = None
_local_attempted = False


@dataclass(frozen=True)
class ModelExtraction:
    references: tuple[str, ...]
    confidence: float
    source: str


def _slug(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', value.lower()).strip('_')


def _local_extract(text: str) -> ModelExtraction | None:
    global _local_model, _local_attempted
    if os.getenv('SCOPE_LOCAL_NER_ENABLED', '0') != '1':
        return None
    try:
        if not _local_attempted:
            _local_attempted = True
            from gliner import GLiNER
            _local_model = GLiNER.from_pretrained(os.getenv('SCOPE_LOCAL_NER_MODEL', 'urchade/gliner_small-v2.1'))
        if _local_model is None:
            return None
        labels = ['company', 'organization', 'product', 'document source', 'dataset', 'location']
        rows = _local_model.predict_entities(text, labels, threshold=float(os.getenv('SCOPE_LOCAL_NER_THRESHOLD', '0.85')))
        values = {_slug(str(row.get('text', ''))) for row in rows if row.get('text')}
        if values:
            return ModelExtraction(tuple(f'entity:{value}' for value in sorted(values)), 0.85, 'local_ner')
    except Exception as exc:
        logger.warning('local scope extraction unavailable: %s', exc)
    return None


def _llm_extract(text: str) -> ModelExtraction | None:
    if os.getenv('SCOPE_LLM_FALLBACK_ENABLED', '0') != '1':
        return None
    endpoint = os.getenv('SCOPE_LLM_ENDPOINT', '').strip()
    api_key = os.getenv('SCOPE_LLM_API_KEY', '').strip()
    model = os.getenv('SCOPE_LLM_MODEL', '').strip()
    if not endpoint or not api_key or not model:
        return None
    instruction = 'Extract every organization, product, document source, dataset, and location that changes the answer. Return JSON only: {entities:[string],confidence:number}.'
    body = {'model': model, 'temperature': 0, 'response_format': {'type': 'json_object'}, 'messages': [{'role': 'system', 'content': instruction}, {'role': 'user', 'content': text}]}
    try:
        request = urllib.request.Request(endpoint, data=json.dumps(body).encode(), headers={'authorization': f'Bearer {api_key}', 'content-type': 'application/json'}, method='POST')
        with urllib.request.urlopen(request, timeout=int(os.getenv('SCOPE_LLM_TIMEOUT_SECONDS', '10'))) as response:
            payload = json.loads(response.read())
        content = payload['choices'][0]['message']['content']
        extracted = json.loads(content)
        confidence = float(extracted.get('confidence', 0))
        minimum = float(os.getenv('SCOPE_LLM_MIN_CONFIDENCE', '0.9'))
        values = {_slug(str(value)) for value in extracted.get('entities', []) if _slug(str(value))}
        if confidence >= minimum and values:
            return ModelExtraction(tuple(f'entity:{value}' for value in sorted(values)), confidence, 'llm')
    except Exception as exc:
        logger.warning('LLM scope extraction unavailable: %s', exc)
    return None


def extract_references(text: str) -> ModelExtraction | None:
    return _local_extract(text) or _llm_extract(text)
