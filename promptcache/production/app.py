import logging
import jwt
import os
from datetime import datetime, timedelta, UTC
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from .db import SessionLocal, initialize_database
from .gateway import complete as production_complete, stream_complete as production_stream_complete
from .rate_limit import RateLimiter, RateLimitExceeded
from .auth import authenticate, bootstrap, create_key, revoke_key, revoke_all_keys, list_keys, reveal_keys
from .accounts import signup, login, current_user, create_workspace
from .config import jwt_secret
import hmac
from .repositories import UsageRepository, prune_expired, purge_cache
from .billing import (accrue_all_fees, accrue_savings_fee, apply_event, billing_summary, checkout, enforce_request_limit,
                      enforce_workspace_limit, portal, user_id_from_token, verify_webhook)
from .provider_connections import (PRESETS, delete_connection, list_connections,
                                   save_connection, test_values)
from ..providers.adapters import embed_provider
from .reliability import enforce_budget, get_policy, update_policy
from ..config.settings import load_settings
from .audit import list_audit, record_audit
from .observability import RequestIdMiddleware, configure_logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
configure_logging()
logger=logging.getLogger("promptcache"); settings=load_settings(); limiter=RateLimiter()
auth_limiter=RateLimiter(limit=int(os.getenv("RATE_LIMIT_AUTH_PER_MINUTE","10")),window_seconds=60,name="auth")
_INSECURE_DEFAULTS={"", "change-me", "development-only", "unsafe-development-secret", "generate-a-fernet-key", "replace-me", "replace-before-production"}

def fail_closed_on_insecure_secrets() -> None:
    """Refuse to boot with default or weak secrets once APP_ENV=production."""
    if os.getenv("APP_ENV", "development").strip().lower() != "production":
        return
    jwt_value = os.getenv("JWT_SECRET", "")
    if jwt_value.strip().lower() in _INSECURE_DEFAULTS or len(jwt_value) < 32:
        raise RuntimeError("JWT_SECRET must be a strong random value (32+ chars) when APP_ENV=production")
    if settings.api_key.strip().lower() in _INSECURE_DEFAULTS:
        raise RuntimeError("ADMIN_API_KEY must be changed from its default when APP_ENV=production")
    if os.getenv("API_KEY_ENC_MASTER_KEY", "").strip().lower() in _INSECURE_DEFAULTS:
        raise RuntimeError("API_KEY_ENC_MASTER_KEY must be configured when APP_ENV=production")

fail_closed_on_insecure_secrets()
app=FastAPI(title="PromptCache API",version="0.1.0")
_cors_origins=[o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS","").split(",") if o.strip()]
_wildcard=not _cors_origins and os.getenv("APP_ENV","development").strip().lower()!="production"
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["*"],
    allow_credentials=not _wildcard,
    allow_methods=["*"],
    allow_headers=["*"],
)
# X-Request-ID on every response + structured access log (JSON when LOG_FORMAT=json).
app.add_middleware(RequestIdMiddleware)
class CompletionRequest(BaseModel):
    # extra="allow": unknown OpenAI params (max_tokens, tools, response_format,
    # stop, seed, ...) flow through model_dump() into the gateway instead of
    # being silently dropped; gateway-only flags are stripped in upstream_body.
    model_config = ConfigDict(extra="allow")
    messages: list[dict] = Field(min_length=1)
    provider: str | None = None
    temperature: float | None = None
    cache: bool = True
    cache_namespace: str = "default"
    stream: bool = False
@app.on_event("startup")
def startup():
 with SessionLocal() as session:
  initialize_database(); bootstrap(session)
  try:
    prune_expired(session, event_retention_days=int(os.getenv("USAGE_RETENTION_DAYS", "90")))
  except Exception:
    logger.warning("cache pruning skipped on startup; tables may not be ready yet")
def tenant(auth):
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(401,"Bearer token required")
    raw=auth.removeprefix("Bearer ").strip()
    with SessionLocal() as session:
        value=authenticate(session,raw)
    if not value: raise HTTPException(401,"Invalid API key")
    return value
@app.get("/health")
def health(): return {"ok":True,"service":"promptcache","mode":"production","providers":[{"id":p["id"],"type":p.get("type"),"model":p.get("model")} for p in settings.providers]}
@app.post("/v1/chat/completions")
def completions(request:CompletionRequest, authorization:str|None=Header(default=None)):
 t=tenant(authorization)
 try:
  with SessionLocal() as session:
   enforce_request_limit(session, t); policy=enforce_budget(session, t)
  limiter.check(t, int(policy['rate_limit_per_minute']))
  if request.stream:
   session=SessionLocal()
   try:
    stream=production_stream_complete(request.model_dump(),t,settings,session)
    first=next(stream)
   except Exception:
    session.close(); raise
   def generate():
    try:
     yield first
     yield from stream
    finally:
     session.close()
   return StreamingResponse(generate(),media_type="text/event-stream",headers={"Cache-Control":"no-cache"})
  with SessionLocal() as session: result=production_complete(request.model_dump(),t,settings,session)
  result["promptcache"]["tenant"]=t; return result
 except RateLimitExceeded: raise HTTPException(429,"Rate limit exceeded") from None
 except HTTPException: raise
 except Exception as exc:
  logger.exception("completion_failed tenant=%s",t); raise HTTPException(502,f"Provider gateway error: {exc}") from exc
@app.get("/v1/models")
def list_models():
    """OpenAI-compatible model listing built from the configured providers."""
    seen: dict[str, dict] = {}
    for provider in settings.providers:
        model = provider.get("model")
        if model and model not in seen:
            seen[model] = {"id": model, "object": "model", "owned_by": provider.get("id", "promptcache")}
    return {"object": "list", "data": list(seen.values())}

class EmbeddingsRequest(BaseModel):
    input: str | list[str] = Field(min_length=1)
    model: str | None = None

@app.post("/v1/embeddings")
def embeddings(request: EmbeddingsRequest, authorization: str | None = Header(default=None)):
    """OpenAI-compatible embeddings endpoint proxied to the configured provider."""
    tenant(authorization)
    if not settings.providers:
        raise HTTPException(503, "No providers configured")
    provider = next((p for p in settings.providers if p.get("model") == request.model), settings.providers[0])
    return embed_provider(provider, {"input": request.input})

@app.post("/v1/cache/purge")
def purge_workspace_cache(authorization: str | None = Header(default=None)):
    """Invalidate every cached response for the authenticated workspace."""
    t = tenant(authorization)
    with SessionLocal() as session:
        deleted = purge_cache(session, t)
    return {"purged": True, "deleted": deleted}

@app.get("/v1/metrics")
def metrics(authorization:str|None=Header(default=None)):
 t=tenant(authorization)
 try:
  with SessionLocal() as session:return UsageRepository(session).totals(t)
 except Exception as exc: raise HTTPException(503,f"Metrics database unavailable: {exc}") from exc




class CreateKeyRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=255)

def require_admin(authorization: str | None) -> None:
    expected = settings.api_key
    if not authorization or not hmac.compare_digest(authorization.removeprefix("Bearer ").strip(), expected):
        raise HTTPException(401, "Invalid admin key")

@app.post("/v1/admin/keys")
def create_tenant_key(request: CreateKeyRequest, authorization: str | None = Header(default=None)):
    require_admin(authorization)
    with SessionLocal() as session:
        raw, expires_at = create_key(session, request.tenant_id)
        record_audit(session, "api_key.create", tenant_id=request.tenant_id,
                     detail={"expires_at": expires_at.isoformat()})
    return {"tenant_id": request.tenant_id, "api_key": raw, "expires_at": expires_at.isoformat(), "warning": "Store this key securely."}

@app.delete("/v1/admin/keys/{key_id}")
def revoke_tenant_key(key_id: int, authorization: str | None = Header(default=None)):
    require_admin(authorization)
    with SessionLocal() as session:
        if not revoke_key(session, key_id): raise HTTPException(404, "API key not found")
        record_audit(session, "api_key.revoke", target=f"key:{key_id}")
    return {"revoked": True, "key_id": key_id}

@app.post("/v1/admin/accrue-fees")
def admin_accrue_fees(authorization: str | None = Header(default=None)):
    """Operator/cron endpoint: accrue savings fees for all workspaces."""
    require_admin(authorization)
    with SessionLocal() as session:
        results = accrue_all_fees(session)
        record_audit(session, "billing.accrue_all_fees", detail={"workspaces": len(results)})
        return {"accrued": results}


@app.post("/v1/billing/savings-fee/accrue")
def user_accrue_savings_fee(authorization: str | None = Header(default=None)):
    """User-facing endpoint: accrue (bill) this user's share of monthly savings."""
    user_id = user_id_from_token(authorization)
    with SessionLocal() as session:
        result = accrue_savings_fee(session, user_id)
        record_audit(session, "billing.accrue_savings_fee", user_id=user_id, detail={
            "billed_now": result.get("billed_now"), "invoice_item_id": result.get("invoice_item_id")})
        return result


class SignupRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=256)

@app.post("/v1/auth/signup", status_code=201)
def register(request: SignupRequest, http_request: Request):
    try:
        auth_limiter.check(http_request.client.host if http_request.client else "unknown")
    except RateLimitExceeded:
        raise HTTPException(429, "Too many signup attempts; try again later") from None
    try:
        with SessionLocal() as session:
            user_id = signup(session, request.email, request.password)
            token = jwt.encode({"sub":str(user_id),"exp":datetime.now(UTC)+timedelta(hours=8)},jwt_secret(),algorithm="HS256")
            record_audit(session, "auth.signup", user_id=user_id, target=request.email)
        return {"access_token": token, "token_type": "bearer", "expires_in": 28800, "message": "Account created. You are now logged in."}
    except Exception as exc:
        raise HTTPException(400, "Unable to create account") from exc

class CreateWorkspaceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)

@app.post("/v1/workspaces")
def create_ws(request: CreateWorkspaceRequest, authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401,"Bearer token required")
    try:
        payload = jwt.decode(authorization.removeprefix("Bearer ").strip(), jwt_secret(), algorithms=["HS256"])
        user_id = int(payload["sub"])
        with SessionLocal() as session:
            enforce_workspace_limit(session, user_id)
            tenant_id, api_key, expires_at = create_workspace(session, user_id, request.name)
            record_audit(session, "workspace.create", tenant_id=tenant_id, user_id=user_id, target=request.name)
        return {"tenant_id": tenant_id, "name": request.name, "api_key": api_key, "expires_at": expires_at, "message": "Workspace created. Your API key is saved in your dashboard and can be re-revealed anytime."}
    except HTTPException: raise
    except Exception as exc: raise HTTPException(400, "Unable to create workspace") from exc

@app.post("/v1/workspaces/{tenant_id}/regenerate-key")
def regenerate_ws_key(tenant_id: str, authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401,"Bearer token required")
    try:
        payload = jwt.decode(authorization.removeprefix("Bearer ").strip(), jwt_secret(), algorithms=["HS256"])
        user_id = int(payload["sub"])
        # Verify the workspace belongs to this user
        with SessionLocal() as session:
            ws = session.execute(text("SELECT id FROM workspaces WHERE tenant_id=:t AND owner_id=:u"), {"t": tenant_id, "u": user_id}).first()
            if not ws: raise HTTPException(404, "Workspace not found")
            revoke_all_keys(session, tenant_id)
            new_key, expires_at = create_key(session, tenant_id)
            record_audit(session, "api_key.regenerate", tenant_id=tenant_id, user_id=user_id)
        return {"tenant_id": tenant_id, "api_key": new_key, "expires_at": expires_at.isoformat(), "message": "New API key generated. Previous key(s) revoked."}
    except HTTPException: raise
    except Exception as exc: raise HTTPException(400, "Unable to regenerate key") from exc

@app.get("/v1/workspaces/{tenant_id}/keys")
def list_ws_keys(tenant_id: str, authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401,"Bearer token required")
    try:
        payload = jwt.decode(authorization.removeprefix("Bearer ").strip(), jwt_secret(), algorithms=["HS256"])
        user_id = int(payload["sub"])
        with SessionLocal() as session:
            ws = session.execute(text("SELECT id FROM workspaces WHERE tenant_id=:t AND owner_id=:u"), {"t": tenant_id, "u": user_id}).first()
            if not ws: raise HTTPException(404, "Workspace not found")
            keys = list_keys(session, tenant_id)
        return {"tenant_id": tenant_id, "keys": keys}
    except HTTPException: raise
    except Exception as exc: raise HTTPException(400, "Unable to list keys") from exc

@app.get("/v1/workspaces/{tenant_id}/keys/reveal")
def reveal_ws_keys(tenant_id: str, authorization: str | None = Header(default=None)):
    """Return decrypted active keys for a workspace the token's user owns."""
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401,"Bearer token required")
    try:
        payload = jwt.decode(authorization.removeprefix("Bearer ").strip(), jwt_secret(), algorithms=["HS256"])
        user_id = int(payload["sub"])
        with SessionLocal() as session:
            ws = session.execute(text("SELECT id FROM workspaces WHERE tenant_id=:t AND owner_id=:u"), {"t": tenant_id, "u": user_id}).first()
            if not ws: raise HTTPException(404, "Workspace not found")
            keys = reveal_keys(session, tenant_id)
            record_audit(session, "api_key.reveal", tenant_id=tenant_id, user_id=user_id,
                         detail={"count": len(keys)})
        return {"tenant_id": tenant_id, "keys": keys}
    except HTTPException: raise
    except Exception as exc: raise HTTPException(400, "Unable to reveal keys") from exc

class LoginRequest(BaseModel):
    email: str
    password: str

@app.post("/v1/auth/login")
def sign_in(request: LoginRequest, http_request: Request):
    try:
        auth_limiter.check(http_request.client.host if http_request.client else "unknown")
    except RateLimitExceeded:
        raise HTTPException(429, "Too many login attempts; try again later") from None
    try:
        with SessionLocal() as session:
            token = login(session, request.email, request.password)
            record_audit(session, "auth.login", target=request.email)
        return {"access_token": token, "token_type": "bearer", "expires_in": 28800}
    except Exception as exc:
        raise HTTPException(401, "Invalid email or password") from exc

@app.get("/v1/me")
def me(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401,"Bearer token required")
    try:
        with SessionLocal() as session: rows = current_user(session, authorization.removeprefix("Bearer ").strip())
        if not rows: raise HTTPException(404,"User not found")
        return {"email": rows[0]["email"], "workspaces": [{"name":r["name"],"tenant_id":r["tenant_id"]} for r in rows if r["tenant_id"]]}
    except HTTPException: raise
    except Exception as exc: raise HTTPException(401,"Invalid or expired token") from exc

class CheckoutRequest(BaseModel):
    plan: str = Field(min_length=1, max_length=32)

class ProviderConnectionRequest(BaseModel):
    provider_type: str = Field(min_length=1, max_length=32)
    name: str | None = Field(default=None, max_length=100)
    api_key: str = Field(min_length=4, max_length=500)
    base_url: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=200)
    input_cost_per_million: float = Field(default=0, ge=0)
    output_cost_per_million: float = Field(default=0, ge=0)

class ReliabilityRequest(BaseModel):
    monthly_budget: float = Field(ge=0, le=1000000)
    rate_limit_per_minute: int = Field(ge=1, le=100000)
    max_retries: int = Field(ge=0, le=5)
    timeout_seconds: int = Field(ge=5, le=120)

class AlertSettingsRequest(BaseModel):
    enabled: bool = True
    budget_percent: int = Field(ge=1, le=100)
    latency_ms: int = Field(ge=100, le=300000)
    cache_hit_percent: int = Field(ge=0, le=100)
    webhook_url: str | None = Field(default=None, max_length=1000)

@app.get('/v1/billing')
def get_billing(authorization: str | None = Header(default=None)):
    user_id = user_id_from_token(authorization)
    with SessionLocal() as session:
        return billing_summary(session, user_id)

@app.get('/v1/workspaces/{tenant_id}/requests')
def request_ledger(tenant_id: str, authorization: str | None = Header(default=None),
                   limit: int = Query(default=50, ge=1, le=100), before_id: int | None = Query(default=None, ge=1)):
    user_id = user_id_from_token(authorization)
    with SessionLocal() as session:
        owned = session.execute(text('SELECT 1 FROM workspaces WHERE tenant_id=:tenant AND owner_id=:owner'),
                                {'tenant': tenant_id, 'owner': user_id}).first()
        if not owned:
            raise HTTPException(404, 'Workspace not found')
        result = UsageRepository(session).recent(tenant_id, limit, before_id)
        result['tenant_id'] = tenant_id
        return result

def require_workspace(session, tenant_id: str, user_id: int) -> None:
    owned=session.execute(text('SELECT 1 FROM workspaces WHERE tenant_id=:tenant AND owner_id=:owner'),{'tenant':tenant_id,'owner':user_id}).first()
    if not owned: raise HTTPException(404,'Workspace not found')

@app.get('/v1/provider-presets')
def provider_presets():
    return [{'id':key,**value} for key,value in PRESETS.items()]

@app.get('/v1/workspaces/{tenant_id}/providers')
def get_workspace_providers(tenant_id: str, authorization: str | None = Header(default=None)):
    user_id=user_id_from_token(authorization)
    with SessionLocal() as session:
        require_workspace(session,tenant_id,user_id)
        return {'tenant_id':tenant_id,'providers':list_connections(session,tenant_id)}

@app.get('/v1/workspaces/{tenant_id}/reliability')
def get_workspace_reliability(tenant_id: str, authorization: str | None = Header(default=None)):
    user_id=user_id_from_token(authorization)
    with SessionLocal() as session:
        require_workspace(session,tenant_id,user_id)
        return get_policy(session,tenant_id)

@app.put('/v1/workspaces/{tenant_id}/reliability')
def set_workspace_reliability(tenant_id: str, request: ReliabilityRequest, authorization: str | None = Header(default=None)):
    user_id=user_id_from_token(authorization)
    with SessionLocal() as session:
        require_workspace(session,tenant_id,user_id)
        return update_policy(session,tenant_id,request.model_dump())

@app.post('/v1/workspaces/{tenant_id}/providers')
def connect_workspace_provider(tenant_id: str, request: ProviderConnectionRequest, authorization: str | None = Header(default=None)):
    user_id=user_id_from_token(authorization)
    if request.provider_type not in PRESETS: raise HTTPException(400,'Unsupported provider type')
    with SessionLocal() as session:
        require_workspace(session,tenant_id,user_id)
        connection = save_connection(session,tenant_id,request.model_dump())
        record_audit(session, "provider.connect", tenant_id=tenant_id, user_id=user_id,
                     target=str(connection.get("id")), detail={"provider_type": request.provider_type})
        return connection

@app.post('/v1/workspaces/{tenant_id}/providers/test')
def test_workspace_provider(tenant_id: str, request: ProviderConnectionRequest, authorization: str | None = Header(default=None)):
    user_id=user_id_from_token(authorization)
    with SessionLocal() as session: require_workspace(session,tenant_id,user_id)
    try: return test_values(request.model_dump())
    except Exception as exc: raise HTTPException(400,f'Connection failed: {exc}') from exc

@app.delete('/v1/workspaces/{tenant_id}/providers/{connection_id}')
def disconnect_workspace_provider(tenant_id: str, connection_id: int, authorization: str | None = Header(default=None)):
    user_id=user_id_from_token(authorization)
    with SessionLocal() as session:
        require_workspace(session,tenant_id,user_id)
        if not delete_connection(session,tenant_id,connection_id): raise HTTPException(404,'Provider connection not found')
        record_audit(session, "provider.disconnect", tenant_id=tenant_id, user_id=user_id, target=str(connection_id))
    return {'deleted':True}

@app.get('/v1/workspaces/{tenant_id}/audit')
def workspace_audit(tenant_id: str, authorization: str | None = Header(default=None),
                    limit: int = Query(default=100, ge=1, le=500)):
    """Newest-first audit trail for the workspace (key, provider, and billing actions)."""
    user_id = user_id_from_token(authorization)
    with SessionLocal() as session:
        require_workspace(session, tenant_id, user_id)
        return {"tenant_id": tenant_id, "events": list_audit(session, tenant_id, limit=limit)}

@app.post('/v1/billing/checkout')
def create_checkout(request: CheckoutRequest, authorization: str | None = Header(default=None)):
    user_id = user_id_from_token(authorization)
    with SessionLocal() as session:
        url = checkout(session, user_id, request.plan)
        record_audit(session, "billing.checkout", user_id=user_id, detail={"plan": request.plan})
        return {'url': url}

@app.post('/v1/billing/portal')
def create_portal(authorization: str | None = Header(default=None)):
    user_id = user_id_from_token(authorization)
    with SessionLocal() as session:
        return {'url': portal(session, user_id)}

@app.post('/v1/billing/webhook')
async def stripe_webhook(request: Request):
    payload = await request.body()
    event = verify_webhook(payload, request.headers.get('stripe-signature', ''))
    with SessionLocal() as session:
        apply_event(session, event)
    return {'received': True}

class BaselineRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=255)

@app.put("/v1/workspaces/{tenant_id}/baseline")
def set_baseline(tenant_id: str, request: BaselineRequest, authorization: str | None = Header(default=None)):
    """Point the workspace savings baseline at a specific configured provider."""
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401, "Bearer token required")
    try:
        payload = jwt.decode(authorization.removeprefix("Bearer ").strip(), jwt_secret(), algorithms=["HS256"])
        user_id = int(payload["sub"])
        if not any(p["id"] == request.provider for p in settings.providers): raise HTTPException(400, "Unknown provider: " + request.provider)
        with SessionLocal() as session:
            ws = session.execute(text("SELECT id FROM workspaces WHERE tenant_id=:t AND owner_id=:u"), {"t": tenant_id, "u": user_id}).first()
            if not ws: raise HTTPException(404, "Workspace not found")
            session.execute(text("UPDATE workspaces SET baseline_provider=:p WHERE tenant_id=:t"), {"p": request.provider, "t": tenant_id})
            session.commit()
            return {"tenant_id": tenant_id, "baseline_provider": request.provider, "message": "Savings baseline updated. New requests measure savings against this provider."}
    except HTTPException: raise
    except Exception as exc: raise HTTPException(400, "Unable to set baseline") from exc

@app.get("/v1/workspaces/{tenant_id}/baseline")
def get_baseline(tenant_id: str, authorization: str | None = Header(default=None)):
    """Read the workspace savings baseline provider (or null/404 if unset)."""
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401, "Bearer token required")
    try:
        payload = jwt.decode(authorization.removeprefix("Bearer ").strip(), jwt_secret(), algorithms=["HS256"])
        user_id = int(payload["sub"])
        with SessionLocal() as session:
            ws = session.execute(text("SELECT baseline_provider FROM workspaces WHERE tenant_id=:t AND owner_id=:u"), {"t": tenant_id, "u": user_id}).first()
            if not ws: raise HTTPException(404, "Workspace not found")
            return {"tenant_id": tenant_id, "baseline_provider": ws[0]}
    except HTTPException: raise
    except Exception as exc: raise HTTPException(400, "Unable to read baseline") from exc


