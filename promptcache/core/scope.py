'''Deterministic safety boundaries for semantic cache matching.'''
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any


SCOPE_VERSION = 1

REFERENCE_PATTERNS: dict[str, tuple[str, ...]] = {
    'source:google_docs': (r'\bgoogle\s+docs?\b', r'\bgdocs\b', r'docs\.google\.com'),
    'source:microsoft_jobs': (r'\bmicrosoft\s+jobs?\b', r'\bms\s+careers?\b', r'jobs\.microsoft\.com'),
    'source:amazon_reports': (r'\bamazon\s+reports?\b', r'\bir\.aboutamazon\.com'),
    'entity:microsoft': (r'\bmicrosoft\b', r'\bmsft\b'),
    'entity:google': (r'\bgoogle\b', r'\balphabet\b'),
    'entity:amazon': (r'\bamazon\b',),
    'entity:openai': (r'\bopenai\b',),
}

OPERATIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ('compare', ('compare', 'versus', ' vs ', 'against')),
    ('search', ('search', 'find', 'look up', 'show me', 'latest')),
    ('summarize', ('summarize', 'summary', 'brief')),
    ('extract', ('extract', 'parse', 'list')),
)

COMMON_CAPITALIZED_WORDS = frozenset({
    'A', 'An', 'And', 'Are', 'Can', 'Create', 'Explain', 'Find', 'For', 'How',
    'I', 'In', 'Is', 'It', 'List', 'Please', 'Prepare', 'Search', 'Show', 'The',
    'This', 'What', 'When', 'Where', 'Write', 'You', 'Your',
})


@dataclass(frozen=True)
class SemanticScope:
    fingerprint: str | None
    operation: str
    references: tuple[str, ...]
    reason: str

    @property
    def enabled(self) -> bool:
        return self.fingerprint is not None


def _message_text(messages: list[dict[str, Any]]) -> str:
    return '\n'.join(str(message.get('content', '')) for message in messages)


def _operation(text: str) -> str:
    lowered = text.lower()
    for name, markers in OPERATIONS:
        if any(marker in lowered for marker in markers):
            return name
    return 'general'


def _references(text: str) -> tuple[str, ...]:
    lowered = text.lower()
    found = {
        identifier
        for identifier, patterns in REFERENCE_PATTERNS.items()
        if any(re.search(pattern, lowered) for pattern in patterns)
    }
    return tuple(sorted(found))


def _has_unknown_named_entity(text: str, references: tuple[str, ...]) -> bool:
    known = set()
    for reference in references:
        known.update(reference.split(':', 1)[1].replace('_', ' ').split())
    for candidate in re.findall(r'\b[A-Z][A-Za-z0-9_-]{2,}\b', text):
        if candidate in COMMON_CAPITALIZED_WORDS:
            continue
        if candidate.lower() not in known:
            return True
    return False


def resolve_semantic_scope(messages: list[dict[str, Any]]) -> SemanticScope:
    '''Create a conservative cache boundary without an LLM call.'''
    text = _message_text(messages)
    operation = _operation(text)
    references = _references(text)
    if not references and _has_unknown_named_entity(text, references):
        return SemanticScope(None, operation, references, 'unresolved_named_entity')
    descriptor = {
        'version': SCOPE_VERSION,
        'operation': operation,
        'references': references,
    }
    encoded = json.dumps(descriptor, separators=(',', ':'), sort_keys=True).encode()
    return SemanticScope(sha256(encoded).hexdigest(), operation, references, 'resolved')
