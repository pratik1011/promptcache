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


def test_equivalent_period_words_share_scope_for_the_same_entity_and_metric():
    annual = scope('What is the annual budget of Google?')
    yearly = scope('What is the yearly budget of Google?')
    assert annual.enabled
    assert annual.fingerprint == yearly.fingerprint
    assert annual.filters == ('metric:budget', 'period:annual')


def test_entity_period_and_metric_changes_produce_different_scopes():
    annual_google = scope('What is the annual budget of Google?')
    monthly_google = scope('What is the monthly budget of Google?')
    annual_microsoft = scope('What is the annual budget of Microsoft?')
    annual_revenue_google = scope('What is the annual revenue of Google?')
    assert annual_google.fingerprint != monthly_google.fingerprint
    assert annual_google.fingerprint != annual_microsoft.fingerprint
    assert annual_google.fingerprint != annual_revenue_google.fingerprint


def test_explicit_years_are_part_of_the_scope():
    current = scope('What was the annual budget of Google in 2024?')
    previous = scope('What was the annual budget of Google in 2023?')
    assert current.fingerprint != previous.fingerprint
