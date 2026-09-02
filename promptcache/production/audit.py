"""Append-only audit trail for security-relevant actions.

Every write is best-effort: an audit failure logs a warning but never breaks
the request it records. Reads are owner-scoped via the API layer.
"""
import json
import logging

from sqlalchemy import text

logger = logging.getLogger("promptcache")


def record_audit(session, action: str, tenant_id: str | None = None, user_id: int | None = None,
                 target: str = "", detail: dict | None = None) -> None:
    """Persist one audit event (action, actor, target, JSON detail)."""
    try:
        params = {"tenant": tenant_id, "user": user_id, "action": action, "target": target,
                  "detail": json.dumps(detail or {}, default=str)}
        # Postgres needs an explicit cast from the text parameter to jsonb;
        # SQLite (tests/demo) stores the raw JSON string in a TEXT column.
        placeholder = "CAST(:detail AS jsonb)" if (session.bind and session.bind.dialect.name == "postgresql") else ":detail"
        session.execute(text(
            f"INSERT INTO audit_log (tenant_id, user_id, action, target, detail) "
            f"VALUES (:tenant, :user, :action, :target, {placeholder})"), params)
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.warning("audit write failed for action=%s: %s", action, exc)


def list_audit(session, tenant_id: str, limit: int = 100) -> list[dict]:
    """Newest-first audit events for a workspace."""
    rows = session.execute(text(
        "SELECT id, tenant_id, user_id, action, target, detail, created_at FROM audit_log "
        "WHERE tenant_id=:tenant ORDER BY id DESC LIMIT :limit"),
        {"tenant": tenant_id, "limit": limit}).mappings().all()
    return [{"id": row["id"], "tenant_id": row["tenant_id"], "user_id": row["user_id"],
             "action": row["action"], "target": row["target"], "detail": _loads(row["detail"]),
             "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"])}
            for row in rows]


def _loads(value) -> dict:
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value) if value else {}
    except (TypeError, ValueError):
        return {}
