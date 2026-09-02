import copy
import json
import time
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from ..cache.semantic import key, normalize_prompt
from ..core.safety import contains_secret
from ..providers.adapters import call_provider, stream_provider, tokens
from ..providers.embeddings import build_embedding_provider
from ..routing.router import select_provider
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
    context = {"provider": provider["id"], "model": provider.get("model"), "temperature": request.get("temperature")}
    cache_key = key(prompt, request.get("cache_namespace", "default"), context)
    cache, usage = CacheRepository(session), UsageRepository(session)
    caching = bool(request.get("cache", True)) and not contains_secret(request)
    vector = None
    hit = cache.exact(tenant, cache_key) if caching else None
    semantic_score = None
    if hit is None and caching:
        embedder = _get_embedder()
        if embedder is not None:
            try:
                vector = embedder.embed(prompt)
                match = next(((record, score) for record, score in cache.semantic(tenant, vector)
                              if record.provider == provider["id"] and float(score) >= settings.similarity_threshold), None)
                if match: hit, semantic_score = match
            except Exception:
                logger.warning("semantic matching failed tenant=%s; falling back to exact cache", tenant)
                vector = None
    actual = 0.0
    if hit:
        response = copy.deepcopy(hit.response); baseline = float(hit.cost)
        response["promptcache"] = {"cached": True, "match": "semantic" if semantic_score is not None else "exact", "similarity": float(semantic_score) if semantic_score is not None else 1.0, "provider": hit.provider, "complexity": complexity}
    else:
        response = None; last_error = None
        for candidate in [item for p in [provider]+[p for p in settings.providers if p['id']!=provider['id']] for item in [p]*(settings.max_retries+1)]:
            try: response = call_provider(candidate, request); provider = candidate; break
            except Exception as exc: last_error = exc
        if response is None: raise RuntimeError(f"All configured providers failed: {last_error}")
        u = response.get("usage", {}); p = u.get("prompt_tokens", tokens(prompt)); o = u.get("completion_tokens", tokens(response.get("choices", [{}])[0].get("message", {}).get("content", "")))
        actual = (p*provider.get("inputCostPerMillion",0)+o*provider.get("outputCostPerMillion",0))/1e6
        premium=_baseline_provider(settings, session, tenant); baseline=(p*premium.get("inputCostPerMillion",0)+o*premium.get("outputCostPerMillion",0))/1e6
        response["promptcache"]={"cached":False,"provider":provider["id"],"complexity":complexity,"baselineProvider":premium["id"]}
        if caching: cache.save(tenant_id=tenant, cache_key=cache_key, prompt=prompt, response=response, embedding=vector, provider=provider["id"], cost=actual, expires_at=datetime.now(timezone.utc)+timedelta(seconds=settings.cache_ttl_seconds))
    event={"tenant_id":tenant,"provider":response["promptcache"]["provider"],"cached":bool(hit),"actual_cost":actual,"baseline_cost":baseline,"saved":max(0,baseline-actual),"latency_ms":round((time.monotonic()-start)*1000)}; usage.record(**event); response["promptcache"]["cost"]=event; return response


def stream_complete(request, tenant, settings, session):
    """SSE passthrough for stream:true requests.

    Streaming bypasses the cache in both directions; usage is still recorded
    from the accumulated response text once the stream ends."""
    settings=runtime_settings(session,tenant,settings)
    start=time.monotonic()
    messages=request["messages"];prompt=normalize_prompt(messages)
    provider,complexity=select_provider(messages,settings.providers,settings.routes,request.get("provider"))
    usage=UsageRepository(session)
    stream=None;last_error=None
    for candidate in [item for p in [provider]+[p for p in settings.providers if p['id']!=provider['id']] for item in [p]*(settings.max_retries+1)]:
        try:
            stream=stream_provider(candidate,request)
            first=next(stream)
            provider=candidate
            break
        except Exception as exc:
            last_error=exc
            stream=None
    if stream is None: raise RuntimeError(f"All configured providers failed: {last_error}")
    parts=[]
    def _scan(chunk):
        if chunk.startswith("data: ") and chunk!="data: [DONE]":
            try: payload=json.loads(chunk[6:])
            except ValueError: return
            delta=payload.get("choices",[{}])[0].get("delta",{}).get("content","")
            if delta: parts.append(delta)
    yield first
    _scan(first)
    for chunk in stream:
        yield chunk
        _scan(chunk)
    content="".join(parts)
    p=tokens(prompt);o=tokens(content)
    actual=(p*provider.get("inputCostPerMillion",0)+o*provider.get("outputCostPerMillion",0))/1e6
    premium=_baseline_provider(settings,session,tenant);baseline=(p*premium.get("inputCostPerMillion",0)+o*premium.get("outputCostPerMillion",0))/1e6
    event={"tenant_id":tenant,"provider":provider["id"],"cached":False,"actual_cost":actual,"baseline_cost":baseline,"saved":max(0,baseline-actual),"latency_ms":round((time.monotonic()-start)*1000)}
    usage.record(**event)
