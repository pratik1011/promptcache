"""Persistence operations used by the production gateway."""
from datetime import datetime, timedelta, timezone
from sqlalchemy import delete, func, select, text
from .db import CacheRecord, UsageEvent

def prune_expired(session, event_retention_days: int = 90) -> dict:
    """Delete expired cache entries and age out old usage history.

    Run at startup so the cache and event ledger do not grow without bound.
    Returns the number of rows removed from each table.
    """
    now = datetime.now(timezone.utc)
    cache_deleted = session.execute(delete(CacheRecord).where(CacheRecord.expires_at < now)).rowcount
    cutoff = now - timedelta(days=event_retention_days)
    usage_deleted = session.execute(delete(UsageEvent).where(UsageEvent.created_at < cutoff)).rowcount
    session.commit()
    return {"cache_records_deleted": cache_deleted, "usage_events_deleted": usage_deleted}

class CacheRepository:
    def __init__(self, session):
        self.session = session

    def exact(self, tenant_id: str, cache_key: str) -> CacheRecord | None:
        query = select(CacheRecord).where(
            CacheRecord.tenant_id == tenant_id,
            CacheRecord.cache_key == cache_key,
            CacheRecord.expires_at > datetime.now(timezone.utc),
        )
        return self.session.scalar(query)

    def semantic(self, tenant_id: str, embedding: list[float], limit: int = 5) -> list[tuple[CacheRecord, float]]:
        """Return non-expired tenant records ordered by cosine similarity."""
        query = select(CacheRecord, (1 - CacheRecord.embedding.cosine_distance(embedding)).label("similarity")).where(
            CacheRecord.tenant_id == tenant_id,
            CacheRecord.expires_at > datetime.now(timezone.utc),
            CacheRecord.embedding.is_not(None),
        ).order_by(text("similarity DESC")).limit(limit)
        return list(self.session.execute(query).all())

    def save(self, **values) -> CacheRecord:
        record = CacheRecord(**values)
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

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
        query = select(
            func.count(UsageEvent.id),
            func.coalesce(func.sum(UsageEvent.saved), 0),
            func.coalesce(func.sum(UsageEvent.actual_cost), 0),
            func.coalesce(func.sum(UsageEvent.baseline_cost), 0),
        ).where(UsageEvent.tenant_id == tenant_id)
        requests, saved, actual, baseline = self.session.execute(query).one()
        hit_query = select(func.count(UsageEvent.id)).where(UsageEvent.tenant_id == tenant_id, UsageEvent.cached.is_(True))
        hits = self.session.scalar(hit_query) or 0
        provider_rows = self.session.execute(select(UsageEvent.provider, func.count(UsageEvent.id), func.sum(UsageEvent.actual_cost), func.sum(UsageEvent.saved)).where(UsageEvent.tenant_id == tenant_id).group_by(UsageEvent.provider)).all()
        daily_rows = self.session.execute(select(func.date(UsageEvent.created_at), func.count(UsageEvent.id), func.sum(UsageEvent.actual_cost), func.sum(UsageEvent.saved)).where(UsageEvent.tenant_id == tenant_id).group_by(func.date(UsageEvent.created_at)).order_by(func.date(UsageEvent.created_at))).all()
        return {"requests": requests, "cache_hits": hits, "cache_hit_rate": hits / requests if requests else 0, "saved": float(saved), "actual_cost": float(actual), "baseline_cost": float(baseline), "by_provider": [{"provider": p, "requests": n, "actual_cost": float(c or 0), "saved": float(x or 0)} for p,n,c,x in provider_rows], "by_day": [{"date": str(d), "requests": n, "actual_cost": float(c or 0), "saved": float(x or 0)} for d,n,c,x in daily_rows]}




