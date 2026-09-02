import hashlib
import os
import secrets
from datetime import datetime, timedelta, UTC
from sqlalchemy import text
from cryptography.fernet import Fernet, InvalidToken

def key_hash(value: str) -> str:
    """Fast, index-friendly hash for API keys (they are high-entropy random values)."""
    salt = os.getenv("API_KEY_HASH_SALT", "replace-before-production").encode()
    return "sha256:" + hashlib.sha256(salt + value.encode()).hexdigest()

def _legacy_scrypt_hash(value: str) -> str:
    """Pre-fast-hash scrypt digests; kept so older keys keep authenticating."""
    salt = os.getenv("API_KEY_HASH_SALT", "replace-before-production").encode()
    return hashlib.scrypt(value.encode(), salt=salt, n=16384, r=8, p=1).hex()

def _fernet():
    master = os.getenv("API_KEY_ENC_MASTER_KEY", "").strip()
    return Fernet(master.encode()) if master else None

def encrypt_key(raw: str) -> str | None:
    f = _fernet()
    return f.encrypt(raw.encode()).decode() if f else None

def decrypt_key(token: str | None) -> str | None:
    f = _fernet()
    if not f or not token:
        return None
    try:
        return f.decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None

KEY_TTL_DAYS = int(os.getenv("API_KEY_TTL_DAYS", "90"))

def create_key(session, tenant_id: str, ttl_days: int | None = None) -> tuple[str, datetime]:
    raw = "pc_" + secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(days=ttl_days or KEY_TTL_DAYS)
    session.execute(text("INSERT INTO api_keys (tenant_id, key_hash, key_encrypted, expires_at) VALUES (:tenant, :hash, :enc, :exp)"),
                    {"tenant": tenant_id, "hash": key_hash(raw), "enc": encrypt_key(raw), "exp": expires})
    session.commit()
    return raw, expires

def _lookup(session, now: datetime, hash_value: str) -> str | None:
    rows = session.execute(
        text("SELECT tenant_id, expires_at FROM api_keys WHERE key_hash=:h AND active=true"),
        {"h": hash_value},
    ).mappings().all()
    for item in rows:
        exp = item["expires_at"]
        if isinstance(exp, str):
            try: exp = datetime.fromisoformat(exp)
            except ValueError: exp = None
        if exp is not None and exp.tzinfo is None:
            exp = exp.replace(tzinfo=UTC)
        if exp is not None and exp < now:
            return None
        return item["tenant_id"]
    return None

def authenticate(session, raw: str) -> str | None:
    """Resolve an API key to its tenant via an indexed exact-hash lookup."""
    now = datetime.now(UTC)
    tenant = _lookup(session, now, key_hash(raw))
    if tenant is not None:
        return tenant
    return _lookup(session, now, _legacy_scrypt_hash(raw))

def revoke_key(session, key_id: int) -> bool:
    result = session.execute(text("UPDATE api_keys SET active=false WHERE id=:id"), {"id": key_id})
    session.commit()
    return result.rowcount == 1

def revoke_all_keys(session, tenant_id: str) -> None:
    session.execute(text("UPDATE api_keys SET active=false, last_rotated_at=:now WHERE tenant_id=:tenant AND active=true"),
                    {"tenant": tenant_id, "now": datetime.now(UTC)})
    session.commit()

def list_keys(session, tenant_id: str) -> list[dict]:
    rows = session.execute(text("SELECT id, tenant_id, active, created_at, expires_at, last_rotated_at FROM api_keys WHERE tenant_id=:tenant ORDER BY created_at DESC"),
                          {"tenant": tenant_id}).mappings().all()
    now = datetime.now(UTC)
    result = []
    for r in rows:
        exp = r["expires_at"]
        if exp is not None and exp.tzinfo is None:
            exp = exp.replace(tzinfo=UTC)
        days_left = (exp - now).days if exp else None
        result.append({
            "id": r["id"],
            "active": r["active"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "expires_at": exp.isoformat() if exp else None,
            "days_remaining": days_left,
            "expired": exp is not None and exp < now,
        })
    return result

def reveal_keys(session, tenant_id: str) -> list[dict]:
    """Decrypt and return active, unexpired keys for a tenant (Stripe-style reveal).

    Rows created before encrypted storage (or when no master key is configured)
    have no recoverable material and are skipped. Each successful reveal stamps
    last_revealed_at for auditing.
    """
    rows = session.execute(text(
        "SELECT id, key_encrypted, created_at, expires_at FROM api_keys "
        "WHERE tenant_id=:tenant AND active=true AND (expires_at IS NULL OR expires_at > now()) "
        "ORDER BY created_at DESC"), {"tenant": tenant_id}).mappings().all()
    now = datetime.now(UTC)
    revealed = []
    for r in rows:
        raw = decrypt_key(r["key_encrypted"])
        if raw is None:
            continue
        session.execute(text("UPDATE api_keys SET last_revealed_at=:now WHERE id=:id"), {"now": now, "id": r["id"]})
        exp = r["expires_at"]
        if exp is not None and exp.tzinfo is None:
            exp = exp.replace(tzinfo=UTC)
        revealed.append({
            "id": r["id"],
            "key": raw,
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "expires_at": exp.isoformat() if exp else None,
        })
    session.commit()
    return revealed

def bootstrap(session):
    raw = os.getenv("BOOTSTRAP_API_KEY")
    tenant = os.getenv("BOOTSTRAP_TENANT_ID", "local-dev")
    if raw:
        expires = datetime.now(UTC) + timedelta(days=KEY_TTL_DAYS)
        session.execute(text("INSERT INTO api_keys (tenant_id, key_hash, key_encrypted, expires_at) VALUES (:tenant, :hash, :enc, :exp) ON CONFLICT (key_hash) DO UPDATE SET key_encrypted=EXCLUDED.key_encrypted"),
                        {"tenant": tenant, "hash": key_hash(raw), "enc": encrypt_key(raw), "exp": expires})
        session.commit()
