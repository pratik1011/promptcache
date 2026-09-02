import copy
import time
from time import sleep
import logging
from datetime import datetime, timedelta, UTC
from sqlalchemy import text
from ..cache.semantic import key, normalize_prompt
from ..core.safety import contains_secret, pii_redaction_enabled, redact_pii
from ..providers.adapters import cache_chunks, call_provider, stream_provider, tokens
from ..providers.protocol import StreamCapture, upstream_body
from ..providers.embeddings import build_embedding_provider
from ..routing.router import select_provider
from .circuit import breaker, next_delay
from .repositories import CacheRepository, UsageRepository
from .provider_connections import runtime_settings
logger = logging.getLogger("promptcache")
_embedder = None
_embedder_loaded = False

def _baseline_provider(settings, session, tenant: str) -> dict:
    """Savings baseline: the workspace-declared provider, else the most expensive configured one."""
    ident = None
    try:
        row = session.execute(text("SELECT baseline_provider FROM workspaces WHERE tenant_id=:t"), {"t": tenant}).first()
        ident = row[0] if row else None
    except Exception:
        ident = None  # workspaces table not migrated yet
    if ident:
        match = next((p for p in settings.providers if p["id"] == ident), None)
        if match:
            return match
    return max(settings.providers, key=lambda x: x.get("inputCostPerMillion", 0) + x.get("outputCostPerMillion", 0))

def _get_embedder():
    global _embedder, _embedder_loaded
    if not _embedder_loaded:
        _embedder_loaded = True
        _embedder = build_embedding_provider()
    return _embedder

def complete(request, tenant, settings, session):
    settings = runtime_settings(session, tenant, settings)
    start = time.monotonic()
    messages = request["messages"]; prompt = normalize_prompt(messages)
    provider, complexity = select_provider(messages, settings.providers, settings.routes, request.get("provider"))
    # Tool calling / JSON mode change the output for an identical prompt, so the
    # cache context must distinguish them (parity with the demo gateway).
    context = {"provider": provider["id"], "model": provider.get("model"), "temperature": request.get("temperature"),
               "tools": repr(request.get("tools")), "response_format": repr(request.get("response_format"))}
    cache_key = key(prompt, request.get("cache_namespace", "default"), context)
    cache, usage = CacheRepository(session), UsageRepository(session)
    caching = bool(request.get("cache", True)) and not contains_secret(request)
    vector = None
    hit = cache.exact(tenant, cache_key) if caching else None
    semantic_score = None
    if hit is None and caching:
        try:
            embedder = _get_embedder()
            if embedder is not None:
                vector = embedder.embed(prompt)
                match = next(((record, score) for record, score in cache.semantic(tenant, vector)
                              if record.provider == provider["id"] and float(score) >= settings.similarity_threshold), None)
                if match: hit, semantic_score = match
        except Exception:
            logger.warning("semantic matching failed tenant=%s; falling back to exact cache", tenant)
            vector = None
    actual = 0.0
    response: dict | None
    if hit:
        response = copy.deepcopy(hit.response); baseline = float(hit.cost)
        response["promptcache"] = {"cached": True, "match": "semantic" if semantic_score is not None else "exact", "similarity": float(semantic_score) if semantic_score is not None else 1.0, "provider": hit.provider, "complexity": complexity}
    else:
        response = None; last_error: Exception | None = None
        candidates = [provider] + [p for p in settings.providers if p['id'] != provider['id']]
        attempts = int(settings.max_retries) + 1
        generation = 0
        for candidate in candidates:
            for retry in range(attempts):
                if not breaker.allow(candidate["id"]):
                    last_error = RuntimeError(f"provider {candidate['id']} is temporarily open in the circuit breaker")
                    continue
                try:
                    response = call_provider(candidate, upstream_body(request, candidate["model"]))
                    breaker.record_success(candidate["id"])
                    provider = candidate
                    break
                except Exception as exc:
                    breaker.record_failure(candidate["id"])
                    last_error = exc
                    if generation < len(candidates) * attempts - 1:
                        sleep(next_delay(retry))
                generation += 1
            if response is not None:
                break
        if response is None: raise RuntimeError(f"All configured providers failed: {last_error}")
        u = response.get("usage", {}); p = u.get("prompt_tokens", tokens(prompt)); o = u.get("completion_tokens", tokens(response.get("choices", [{}])[0].get("message", {}).get("content", "")))
        actual = (p*provider.get("inputCostPerMillion",0)+o*provider.get("outputCostPerMillion",0))/1e6
        premium=_baseline_provider(settings, session, tenant); baseline=(p*premium.get("inputCostPerMillion",0)+o*premium.get("outputCostPerMillion",0))/1e6
        response["promptcache"]={"cached":False,"provider":provider["id"],"complexity":complexity,"baselineProvider":premium["id"]}
        if caching: cache.save(tenant_id=tenant, cache_key=cache_key, prompt=redact_pii(prompt) if pii_redaction_enabled() else prompt, response=response, embedding=vector, provider=provider["id"], cost=actual, expires_at=datetime.now(UTC)+timedelta(seconds=settings.cache_ttl_seconds))
    event={"tenant_id":tenant,"provider":response["promptcache"]["provider"],"cached":bool(hit),"actual_cost":actual,"baseline_cost":baseline,"saved":max(0,baseline-actual),"latency_ms":round((time.monotonic()-start)*1000)}; usage.record(**event); response["promptcache"]["cost"]=event; return response


def stream_complete(request, tenant, settings, session):
    """SSE passthrough for stream:true requests with exact-cache replay.

    A cached answer for an identical prompt is replayed as SSE and billed as a
    cache hit (no upstream call). Misses stream from the provider with
    breaker/backoff and are stored for exact-match reuse; streams avoid
    computing embeddings so the saved entry is exact-lookup only.
    """
    settings = runtime_settings(session, tenant, settings)
    start = time.monotonic()
    messages = request["messages"]; prompt = normalize_prompt(messages)
    provider, complexity = select_provider(messages, settings.providers, settings.routes, request.get("provider"))
    context = {"provider": provider["id"], "model": provider.get("model"), "temperature": request.get("temperature"),
               "tools": repr(request.get("tools")), "response_format": repr(request.get("response_format"))}
    cache_key = key(prompt, request.get("cache_namespace", "default"), context)
    cache, usage = CacheRepository(session), UsageRepository(session)
    caching = bool(request.get("cache", True)) and not contains_secret(request)
    hit = cache.exact(tenant, cache_key) if caching else None
    if hit:
        content = (hit.response or {}).get("choices", [{}])[0].get("message", {}).get("content", "")
        for chunk in cache_chunks(hit.response or {}, content):
            yield chunk
        baseline = float(hit.cost)
        event = {"tenant_id": tenant, "provider": hit.provider, "cached": True,
                 "actual_cost": 0.0, "baseline_cost": baseline, "saved": baseline,
                 "latency_ms": round((time.monotonic() - start) * 1000)}
        usage.record(**event)
        return
    stream = None; last_error: Exception | None = None
    candidates = [provider] + [p for p in settings.providers if p['id'] != provider['id']]
    attempts = int(settings.max_retries) + 1
    generation = 0
    for candidate in candidates:
        for retry in range(attempts):
            if not breaker.allow(candidate["id"]):
                last_error = RuntimeError(f"provider {candidate['id']} is temporarily open in the circuit breaker")
                continue
            try:
                stream = stream_provider(candidate, upstream_body(request, candidate["model"], stream=True))
                first = next(stream)
                breaker.record_success(candidate["id"])
                provider = candidate
                break
            except Exception as exc:
                breaker.record_failure(candidate["id"])
                last_error = exc
                stream = None
                if generation < len(candidates) * attempts - 1:
                    sleep(next_delay(retry))
            generation += 1
        if stream is not None:
            break
    if stream is None: raise RuntimeError(f"All configured providers failed: {last_error}")
    capture = StreamCapture()
    yield first
    capture.observe(first)
    for chunk in stream:
        yield chunk
        capture.observe(chunk)
    message = capture.snapshot_message()
    content = message.get("content") or ""
    reported = capture.usage or {}
    p=reported.get("prompt_tokens") or tokens(prompt);o=reported.get("completion_tokens") or tokens(content)
    actual=(p*provider.get("inputCostPerMillion",0)+o*provider.get("outputCostPerMillion",0))/1e6
    premium=_baseline_provider(settings,session,tenant);baseline=(p*premium.get("inputCostPerMillion",0)+o*premium.get("outputCostPerMillion",0))/1e6
    if caching:
        cached_response = {
            "id": f"chatcmpl-{tenant[:12]}-{int(time.monotonic() * 1000)}",
            "object": "chat.completion",
            "model": provider.get("model"),
            "choices": [{"message": message, "finish_reason": capture.finish_reason or "stop"}],
            "usage": {"prompt_tokens": p, "completion_tokens": o, "total_tokens": p + o},
        }
        cache.save(tenant_id=tenant, cache_key=cache_key,
                   prompt=redact_pii(prompt) if pii_redaction_enabled() else prompt,
                   response=cached_response, embedding=None, provider=provider["id"], cost=actual,
                   expires_at=datetime.now(UTC)+timedelta(seconds=settings.cache_ttl_seconds))
    event={"tenant_id":tenant,"provider":provider["id"],"cached":False,"actual_cost":actual,"baseline_cost":baseline,"saved":max(0,baseline-actual),"latency_ms":round((time.monotonic()-start)*1000)}
    usage.record(**event)
