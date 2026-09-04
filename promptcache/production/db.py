"""SQLAlchemy persistence for the production deployment."""
import logging
import os
from datetime import date, datetime, UTC
from sqlalchemy import JSON, Boolean, Date, DateTime, Integer, Numeric, String, Text, create_engine, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from pgvector.sqlalchemy import Vector


def sync_database_url(url: str) -> str:
    """Normalize supported PostgreSQL URLs to SQLAlchemy's Psycopg 3 driver."""
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://promptcache:promptcache-dev@localhost:5432/promptcache")
SYNC_DATABASE_URL = sync_database_url(DATABASE_URL)
engine = create_engine(SYNC_DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class CacheRecord(Base):
    __tablename__ = "cache_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(255), index=True)
    cache_key: Mapped[str] = mapped_column(String(128), index=True)
    prompt: Mapped[str] = mapped_column(Text)
    response: Mapped[dict] = mapped_column(JSONB)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384), nullable=True)
    provider: Mapped[str] = mapped_column(String(255))
    cost: Mapped[float] = mapped_column(Numeric(14, 8), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class UsageEvent(Base):
    __tablename__ = "usage_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(255), index=True)
    provider: Mapped[str] = mapped_column(String(255))
    cached: Mapped[bool] = mapped_column(Boolean)
    actual_cost: Mapped[float] = mapped_column(Numeric(14, 8))
    baseline_cost: Mapped[float] = mapped_column(Numeric(14, 8))
    saved: Mapped[float] = mapped_column(Numeric(14, 8))
    latency_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

class DailyUsageRollup(Base):
    """Pre-aggregated per-tenant, per-day, per-provider usage.

    /v1/metrics reads this table for everything before today and queries
    usage_events only for today's live rows, keeping the dashboard fast
    regardless of ledger size.
    """
    __tablename__ = "daily_usage_rollups"
    tenant_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    provider: Mapped[str] = mapped_column(String(255), primary_key=True)
    requests: Mapped[int] = mapped_column(Integer, default=0)
    cache_hits: Mapped[int] = mapped_column(Integer, default=0)
    actual_cost: Mapped[float] = mapped_column(Numeric(14, 8), default=0)
    baseline_cost: Mapped[float] = mapped_column(Numeric(14, 8), default=0)
    saved: Mapped[float] = mapped_column(Numeric(14, 8), default=0)

class UsageRollupState(Base):
    """Per-tenant high-water mark on usage_events.id so rollups run exactly once."""
    __tablename__ = "usage_rollup_state"
    tenant_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    last_event_id: Mapped[int] = mapped_column(Integer, default=0)

class AuditLog(Base):
    """Append-only record of security-relevant actions (key reveals, provider
    changes, billing events). Written via raw SQL by .audit.record_audit."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(128))
    target: Mapped[str] = mapped_column(String(255), default="")
    detail: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)
    try:
        with engine.begin() as conn:
            conn.execute(text('ALTER TABLE users ADD COLUMN IF NOT EXISTS plan TEXT NOT NULL DEFAULT \'developer\''))
            conn.execute(text('ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_status TEXT NOT NULL DEFAULT \'free\''))
            conn.execute(text('ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT'))
            conn.execute(text('ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_subscription_id TEXT'))
            conn.execute(text('ALTER TABLE users ADD COLUMN IF NOT EXISTS current_period_end TIMESTAMPTZ'))
            conn.execute(text('CREATE TABLE IF NOT EXISTS workspace_members (id BIGSERIAL PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES workspaces(tenant_id) ON DELETE CASCADE, user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE, role TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE (tenant_id,user_id))'))
            conn.execute(text('CREATE INDEX IF NOT EXISTS workspace_members_user_idx ON workspace_members(user_id,tenant_id)'))
            conn.execute(text('CREATE TABLE IF NOT EXISTS workspace_invitations (id BIGSERIAL PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES workspaces(tenant_id) ON DELETE CASCADE, email TEXT NOT NULL, role TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE, inviter_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires_at TIMESTAMPTZ NOT NULL, accepted_at TIMESTAMPTZ, revoked_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now())'))
            conn.execute(text('CREATE INDEX IF NOT EXISTS workspace_invitations_tenant_idx ON workspace_invitations(tenant_id,email)'))
            conn.execute(text('''CREATE TABLE IF NOT EXISTS workspace_providers (
                id BIGSERIAL PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES workspaces(tenant_id) ON DELETE CASCADE,
                provider_type TEXT NOT NULL, name TEXT NOT NULL, base_url TEXT NOT NULL, model TEXT NOT NULL,
                api_key_encrypted TEXT NOT NULL, input_cost_per_million NUMERIC(14,6) NOT NULL DEFAULT 0,
                output_cost_per_million NUMERIC(14,6) NOT NULL DEFAULT 0, active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now())'''))
            conn.execute(text('CREATE INDEX IF NOT EXISTS workspace_providers_tenant_idx ON workspace_providers(tenant_id)'))
            conn.execute(text('ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS monthly_budget NUMERIC(14,2) NOT NULL DEFAULT 100'))
            conn.execute(text('ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS rate_limit_per_minute INTEGER NOT NULL DEFAULT 60'))
            conn.execute(text('ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS max_retries INTEGER NOT NULL DEFAULT 1'))
            conn.execute(text('ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS timeout_seconds INTEGER NOT NULL DEFAULT 30'))
            conn.execute(text('ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS alerts_enabled BOOLEAN NOT NULL DEFAULT TRUE'))
            conn.execute(text('ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS budget_alert_percent INTEGER NOT NULL DEFAULT 80'))
            conn.execute(text('ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS latency_alert_ms INTEGER NOT NULL DEFAULT 5000'))
            conn.execute(text('ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS cache_hit_alert_percent INTEGER NOT NULL DEFAULT 20'))
            conn.execute(text('ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS webhook_url_encrypted TEXT'))
            conn.execute(text('''CREATE TABLE IF NOT EXISTS notifications(id BIGSERIAL PRIMARY KEY,
                tenant_id TEXT NOT NULL REFERENCES workspaces(tenant_id) ON DELETE CASCADE,kind TEXT NOT NULL,
                title TEXT NOT NULL,message TEXT NOT NULL,severity TEXT NOT NULL DEFAULT 'info',read_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now())'''))
            conn.execute(text('CREATE INDEX IF NOT EXISTS notifications_tenant_idx ON notifications(tenant_id,id DESC)'))
            conn.execute(text('CREATE INDEX IF NOT EXISTS cache_records_expires_idx ON cache_records (expires_at)'))
            conn.execute(text('CREATE INDEX IF NOT EXISTS usage_events_created_idx ON usage_events (created_at)'))
            conn.execute(text('ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS baseline_provider TEXT'))
            conn.execute(text('''CREATE TABLE IF NOT EXISTS daily_usage_rollups (
                tenant_id TEXT NOT NULL, day DATE NOT NULL, provider TEXT NOT NULL,
                requests INTEGER NOT NULL DEFAULT 0, cache_hits INTEGER NOT NULL DEFAULT 0,
                actual_cost NUMERIC(14,8) NOT NULL DEFAULT 0, baseline_cost NUMERIC(14,8) NOT NULL DEFAULT 0,
                saved NUMERIC(14,8) NOT NULL DEFAULT 0, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (tenant_id, day, provider))'''))
            conn.execute(text('''CREATE TABLE IF NOT EXISTS usage_rollup_state (
                tenant_id TEXT PRIMARY KEY, last_event_id INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now())'''))
            conn.execute(text('''CREATE TABLE IF NOT EXISTS audit_log (
                id BIGSERIAL PRIMARY KEY, tenant_id TEXT, user_id BIGINT,
                action TEXT NOT NULL, target TEXT NOT NULL DEFAULT '',
                detail JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now())'''))
            conn.execute(text('CREATE INDEX IF NOT EXISTS audit_log_tenant_idx ON audit_log (tenant_id, id DESC)'))
            conn.execute(text('CREATE TABLE IF NOT EXISTS product_feedback (id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE, tenant_id TEXT REFERENCES workspaces(tenant_id) ON DELETE CASCADE, category TEXT NOT NULL, message TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now())'))
            conn.execute(text('ALTER TABLE product_feedback ADD COLUMN IF NOT EXISTS tenant_id TEXT REFERENCES workspaces(tenant_id) ON DELETE CASCADE'))
            conn.execute(text('CREATE INDEX IF NOT EXISTS product_feedback_created_idx ON product_feedback(created_at DESC)'))
            conn.execute(text('CREATE INDEX IF NOT EXISTS product_feedback_tenant_idx ON product_feedback(tenant_id, created_at DESC)'))
    except Exception as exc:
        # workspaces table is provisioned by schema.sql in production deployments;
        # log instead of silently swallowing real migration failures. The audit
        # and rollup tables are created by Base.metadata.create_all above.
        logging.getLogger("promptcache").warning("schema patch skipped: %s", exc)
