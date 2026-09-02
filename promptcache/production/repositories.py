"""Persistence operations used by the production gateway."""
import logging
import os
import time
from datetime import date, datetime, timedelta, UTC
from sqlalchemy import case, delete, func, select, text
from .db import CacheRecord, DailyUsageRollup, UsageEvent, UsageRollupState

logger = logging.getLogger("promptcache")

def prune_expired(session, event_retention_days: int = 90) -> dict:
    """Delete expired cache entries and age out old usage history.

    Run at startup so the cache and event ledger do not grow without bound.
    Returns the number of rows removed from each table.
    """
    now = datetime.now(UTC)
    cache_deleted = session.execute(delete(CacheRecord).where(CacheRecord.expires_at < now)).rowcount
    cutoff = now - timedelta(days=event_retention_days)
    usage_deleted = session.execute(delete(UsageEvent).where(UsageEvent.created_at < cutoff)).rowcount
    rollups_deleted = session.execute(delete(DailyUsageRollup).where(DailyUsageRollup.day < cutoff.date())).rowcount
    session.commit()
    return {"cache_records_deleted": cache_deleted, "usage_events_deleted": usage_deleted,
            "rollup_days_deleted": rollups_deleted}

def rollup_daily(session, tenant_id: str | None = None) -> dict:
    """Fold usage_events into daily_usage_rollups incrementally.

    A per-tenant high-water mark on usage_events.id (usage_rollup_state) makes
    each event aggregate exactly once; the state row is locked FOR UPDATE so
    concurrent workers cannot double-count. Events from today stay in the
    ledger and are rolled up on the first pass after midnight.
    """
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    if tenant_id is not None:
        scopes = [(tenant_id,)]
    else:
        scopes = [tuple(row) for row in session.execute(select(UsageEvent.tenant_id).distinct())]
    events_rolled = 0
    for (scope_tenant,) in scopes:
        state = session.execute(
            select(UsageRollupState).where(UsageRollupState.tenant_id == scope_tenant).with_for_update()
        ).scalar_one_or_none()
        watermark = state.last_event_id if state else 0
        batch_max = session.scalar(select(func.max(UsageEvent.id)).where(
            UsageEvent.tenant_id == scope_tenant,
            UsageEvent.id > watermark,
            UsageEvent.created_at < today_start,
        )) or 0
        if batch_max <= watermark:
            continue
        rows = session.execute(
            select(
                UsageEvent.provider,
                func.date(UsageEvent.created_at),
                func.count(UsageEvent.id),
                func.sum(case((UsageEvent.cached.is_(True), 1), else_=0)),
                func.coalesce(func.sum(UsageEvent.actual_cost), 0),
                func.coalesce(func.sum(UsageEvent.baseline_cost), 0),
                func.coalesce(func.sum(UsageEvent.saved), 0),
            ).where(UsageEvent.tenant_id == scope_tenant,
                    UsageEvent.id > watermark,
                    UsageEvent.id <= batch_max,
                    UsageEvent.created_at < today_start)
            .group_by(UsageEvent.provider, func.date(UsageEvent.created_at))
        ).all()
        for provider, day, requests, hits, actual, baseline, saved in rows:
            day_value = day if isinstance(day, date) else datetime.strptime(str(day)[:10], "%Y-%m-%d").date()
            existing = session.get(DailyUsageRollup, {"tenant_id": scope_tenant, "day": day_value, "provider": provider})
            if existing:
                existing.requests += int(requests or 0)
                existing.cache_hits += int(hits or 0)
                existing.actual_cost += float(actual or 0)
                existing.baseline_cost += float(baseline or 0)
                existing.saved += float(saved or 0)
            else:
                session.add(DailyUsageRollup(
                    tenant_id=scope_tenant, day=day_value, provider=provider,
                    requests=int(requests or 0), cache_hits=int(hits or 0),
                    actual_cost=float(actual or 0), baseline_cost=float(baseline or 0),
                    saved=float(saved or 0)))
            events_rolled += int(requests or 0)
        if state:
            state.last_event_id = int(batch_max)
        else:
            session.add(UsageRollupState(tenant_id=scope_tenant, last_event_id=int(batch_max)))
    session.commit()
    return {"events_rolled": events_rolled}

_ROLLUP_MIN_INTERVAL_SECONDS = 300.0
_rollup_last_run: dict[str, float] = {}

def maybe_rollup(session, tenant_id: str, min_interval_seconds: float | None = None) -> None:
    """Throttled rollup so long-running processes also roll over at midnight.

    Never raises: metrics reads must not fail because the rollup tables are
    missing or briefly locked.
    """
    if min_interval_seconds is None:
        min_interval_seconds = float(os.getenv("USAGE_ROLLUP_INTERVAL_SECONDS", str(_ROLLUP_MIN_INTERVAL_SECONDS)))
    now = time.monotonic()
    if now - _rollup_last_run.get(tenant_id, 0.0) < min_interval_seconds:
        return
    _rollup_last_run[tenant_id] = now
    try:
        rollup_daily(session, tenant_id)
    except Exception as exc:
        session.rollback()
        logger.warning("usage rollup skipped for %s: %s", tenant_id, exc)

class CacheRepository:
    def __init__(self, session):
        self.session = session

    def exact(self, tenant_id: str, cache_key: str) -> CacheRecord | None:
        query = select(CacheRecord).where(
            CacheRecord.tenant_id == tenant_id,
            CacheRecord.cache_key == cache_key,
            CacheRecord.expires_at > datetime.now(UTC),
        )
        return self.session.scalar(query)

    def semantic(self, tenant_id: str, embedding: list[float], limit: int = 5) -> list[tuple[CacheRecord, float]]:
        """Return non-expired tenant records ordered by cosine similarity."""
        query = select(CacheRecord, (1 - CacheRecord.embedding.cosine_distance(embedding)).label("similarity")).where(
            CacheRecord.tenant_id == tenant_id,
            CacheRecord.expires_at > datetime.now(UTC),
            CacheRecord.embedding.is_not(None),
        ).order_by(text("similarity DESC")).limit(limit)
        return list(self.session.execute(query).all())

    def save(self, **values) -> CacheRecord:
        record = CacheRecord(**values)
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

def purge_cache(session, tenant_id: str) -> int:
    """Customer-facing cache purge: drop every cache entry for the tenant."""
    deleted = session.execute(delete(CacheRecord).where(CacheRecord.tenant_id == tenant_id)).rowcount
    session.commit()
    return deleted

class UsageRepository:
    def __init__(self, session):
        self.session = session

    def record(self, **values) -> UsageEvent:
        event = UsageEvent(**values)
        self.session.add(event)
        self.session.commit()
        from .alerts import evaluate_alerts
        evaluate_alerts(self.session, values['tenant_id'], values['latency_ms'])
        return event

    def recent(self, tenant_id: str, limit: int = 50, before_id: int | None = None) -> dict:
        query = select(UsageEvent).where(UsageEvent.tenant_id == tenant_id)
        if before_id is not None:
            query = query.where(UsageEvent.id < before_id)
        rows = list(self.session.scalars(query.order_by(UsageEvent.id.desc()).limit(limit + 1)))
        has_more = len(rows) > limit
        rows = rows[:limit]
        return {
            'items': [{'id': row.id, 'provider': row.provider, 'cached': row.cached,
                       'actual_cost': float(row.actual_cost), 'baseline_cost': float(row.baseline_cost),
                       'saved': float(row.saved), 'latency_ms': row.latency_ms,
                       'created_at': row.created_at.isoformat() if row.created_at else None} for row in rows],
            'next_cursor': rows[-1].id if has_more and rows else None,
        }

    def totals(self, tenant_id: str) -> dict:
        """Dashboard aggregates: pre-aggregated rollups for past days plus
        today's live usage_events, so the ledger size never drives query cost."""
        maybe_rollup(self.session, tenant_id)
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        grand = {"requests": 0, "cache_hits": 0, "saved": 0.0, "actual_cost": 0.0, "baseline_cost": 0.0}
        provider_totals: dict[str, dict] = {}
        day_totals: dict[str, dict] = {}

        def _add(provider, day, requests, hits, actual, baseline, saved) -> None:
            grand["requests"] += int(requests or 0)
            grand["cache_hits"] += int(hits or 0)
            grand["saved"] += float(saved or 0)
            grand["actual_cost"] += float(actual or 0)
            grand["baseline_cost"] += float(baseline or 0)
            entry = provider_totals.setdefault(provider, {"requests": 0, "actual_cost": 0.0, "saved": 0.0})
            entry["requests"] += int(requests or 0)
            entry["actual_cost"] += float(actual or 0)
            entry["saved"] += float(saved or 0)
            if day is not None:
                bucket = day_totals.setdefault(str(day)[:10], {"requests": 0, "actual_cost": 0.0, "saved": 0.0})
                bucket["requests"] += int(requests or 0)
                bucket["actual_cost"] += float(actual or 0)
                bucket["saved"] += float(saved or 0)

        rolled_rows = self.session.execute(
            select(DailyUsageRollup.provider,
                   func.sum(DailyUsageRollup.requests),
                   func.sum(DailyUsageRollup.cache_hits),
                   func.coalesce(func.sum(DailyUsageRollup.actual_cost), 0),
                   func.coalesce(func.sum(DailyUsageRollup.baseline_cost), 0),
                   func.coalesce(func.sum(DailyUsageRollup.saved), 0))
            .where(DailyUsageRollup.tenant_id == tenant_id)
            .group_by(DailyUsageRollup.provider)).all()
        for provider, requests, hits, actual, baseline, saved in rolled_rows:
            _add(provider, None, requests, hits, actual, baseline, saved)

        for day, requests, actual, saved in self.session.execute(
            select(DailyUsageRollup.day,
                   func.sum(DailyUsageRollup.requests),
                   func.coalesce(func.sum(DailyUsageRollup.actual_cost), 0),
                   func.coalesce(func.sum(DailyUsageRollup.saved), 0))
            .where(DailyUsageRollup.tenant_id == tenant_id)
            .group_by(DailyUsageRollup.day)).all():
            bucket = day_totals.setdefault(str(day)[:10], {"requests": 0, "actual_cost": 0.0, "saved": 0.0})
            bucket["requests"] += int(requests or 0)
            bucket["actual_cost"] += float(actual or 0)
            bucket["saved"] += float(saved or 0)

        live_rows = self.session.execute(
            select(UsageEvent.provider,
                   func.count(UsageEvent.id),
                   func.sum(case((UsageEvent.cached.is_(True), 1), else_=0)),
                   func.coalesce(func.sum(UsageEvent.actual_cost), 0),
                   func.coalesce(func.sum(UsageEvent.baseline_cost), 0),
                   func.coalesce(func.sum(UsageEvent.saved), 0))
            .where(UsageEvent.tenant_id == tenant_id,
                   UsageEvent.created_at >= today_start)
            .group_by(UsageEvent.provider)).all()
        today = str(today_start.date())
        for provider, requests, hits, actual, baseline, saved in live_rows:
            _add(provider, today, requests, hits, actual, baseline, saved)

        return {"requests": grand["requests"], "cache_hits": grand["cache_hits"],
                "cache_hit_rate": grand["cache_hits"] / grand["requests"] if grand["requests"] else 0,
                "saved": grand["saved"], "actual_cost": grand["actual_cost"],
                "baseline_cost": grand["baseline_cost"],
                "by_provider": [{"provider": p, "requests": v["requests"],
                                 "actual_cost": v["actual_cost"], "saved": v["saved"]}
                                for p, v in provider_totals.items()],
                "by_day": [{"date": d, "requests": v["requests"], "actual_cost": v["actual_cost"],
                            "saved": v["saved"]} for d, v in sorted(day_totals.items())]}




