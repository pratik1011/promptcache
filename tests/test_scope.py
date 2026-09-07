from promptcache.core.scope import resolve_semantic_scope


def scope(prompt: str):
    return resolve_semantic_scope([{'role': 'user', 'content': prompt}])


def test_known_sources_receive_different_scopes():
    google = scope('Search AI related news from Google Docs')
    microsoft = scope('Search AI related news from Microsoft Jobs')
    assert google.enabled
    assert microsoft.enabled
    assert google.fingerprint != microsoft.fingerprint


def test_multiple_sources_are_order_independent():
    first = scope('Compare Google Docs with Microsoft Jobs for AI news')
    second = scope('Compare Microsoft Jobs with Google Docs for AI news')
    assert first.enabled
    assert first.references == second.references
    assert first.fingerprint == second.fingerprint


def test_unknown_named_entity_disables_semantic_caching():
    result = scope('Prepare a research brief for Acme Robotics')
    assert not result.enabled
    assert result.reason == 'unresolved_named_entity'


def test_general_question_can_use_a_semantic_scope():
    result = scope('How does response caching reduce latency?')
    assert result.enabled
    assert result.operation == 'general'
