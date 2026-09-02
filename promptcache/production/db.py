"""SQLAlchemy persistence for the production deployment."""
import os
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Text, create_engine, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from pgvector.sqlalchemy import Vector

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://promptcache:promptcache-dev@localhost:5432/promptcache")
SYNC_DATABASE_URL = DATABASE_URL.replace("+asyncpg", "+psycopg")
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)
    try:
        with engine.begin() as conn:
            conn.execute(text('ALTER TABLE users ADD COLUMN IF NOT EXISTS plan TEXT NOT NULL DEFAULT \'developer\''))
            conn.execute(text('ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_status TEXT NOT NULL DEFAULT \'free\''))
            conn.execute(text('ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT'))
            conn.execute(text('ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_subscription_id TEXT'))
            conn.execute(text('ALTER TABLE users ADD COLUMN IF NOT EXISTS current_period_end TIMESTAMPTZ'))
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
            conn.execute(text("ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS baseline_provider TEXT"))
    except Exception:
        pass  # workspaces table is provisioned by schema.sql in production deployments
