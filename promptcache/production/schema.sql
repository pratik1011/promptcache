CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS cache_records (
  id BIGSERIAL PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  cache_key TEXT NOT NULL,
  prompt TEXT NOT NULL,
  response JSONB NOT NULL,
  embedding vector(384),
  provider TEXT NOT NULL,
  cost NUMERIC(14,8) NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL,
  UNIQUE (tenant_id, cache_key)
);
CREATE INDEX IF NOT EXISTS cache_records_tenant_idx ON cache_records (tenant_id);
CREATE TABLE IF NOT EXISTS usage_events (
  id BIGSERIAL PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  cached BOOLEAN NOT NULL,
  actual_cost NUMERIC(14,8) NOT NULL,
  baseline_cost NUMERIC(14,8) NOT NULL,
  saved NUMERIC(14,8) NOT NULL,
  latency_ms INTEGER NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS usage_events_tenant_date_idx ON usage_events (tenant_id, created_at);
CREATE INDEX IF NOT EXISTS cache_records_expires_idx ON cache_records (expires_at);
CREATE INDEX IF NOT EXISTS usage_events_created_idx ON usage_events (created_at);

-- Pre-aggregated daily usage powering /v1/metrics without scanning the ledger.
CREATE TABLE IF NOT EXISTS daily_usage_rollups (
  tenant_id TEXT NOT NULL,
  day DATE NOT NULL,
  provider TEXT NOT NULL,
  requests INTEGER NOT NULL DEFAULT 0,
  cache_hits INTEGER NOT NULL DEFAULT 0,
  actual_cost NUMERIC(14,8) NOT NULL DEFAULT 0,
  baseline_cost NUMERIC(14,8) NOT NULL DEFAULT 0,
  saved NUMERIC(14,8) NOT NULL DEFAULT 0,
  PRIMARY KEY (tenant_id, day, provider)
);
CREATE TABLE IF NOT EXISTS usage_rollup_state (
  tenant_id TEXT PRIMARY KEY,
  last_event_id BIGINT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS daily_usage_rollups_tenant_day_idx ON daily_usage_rollups (tenant_id, day);
CREATE TABLE IF NOT EXISTS audit_log (
  id BIGSERIAL PRIMARY KEY,
  tenant_id TEXT,
  user_id BIGINT,
  action TEXT NOT NULL,
  target TEXT NOT NULL DEFAULT '',
  detail JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audit_log_tenant_idx ON audit_log (tenant_id, id DESC);

CREATE TABLE IF NOT EXISTS api_keys (
  id BIGSERIAL PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  key_hash TEXT NOT NULL UNIQUE,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ,
  last_rotated_at TIMESTAMPTZ,
  key_encrypted TEXT,
  last_revealed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS api_keys_tenant_idx ON api_keys (tenant_id);

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'api_keys' AND column_name = 'expires_at') THEN
    ALTER TABLE api_keys ADD COLUMN expires_at TIMESTAMPTZ;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'api_keys' AND column_name = 'last_rotated_at') THEN
    ALTER TABLE api_keys ADD COLUMN last_rotated_at TIMESTAMPTZ;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'api_keys' AND column_name = 'key_encrypted') THEN
    ALTER TABLE api_keys ADD COLUMN key_encrypted TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'api_keys' AND column_name = 'last_revealed_at') THEN
    ALTER TABLE api_keys ADD COLUMN last_revealed_at TIMESTAMPTZ;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS users (
  id BIGSERIAL PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS workspaces (
  id BIGSERIAL PRIMARY KEY,
  owner_id BIGINT NOT NULL REFERENCES users(id),
  name TEXT NOT NULL,
  tenant_id TEXT NOT NULL UNIQUE,
  baseline_provider TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS workspace_providers (
  id BIGSERIAL PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES workspaces(tenant_id) ON DELETE CASCADE,
  provider_type TEXT NOT NULL,
  name TEXT NOT NULL,
  base_url TEXT NOT NULL,
  model TEXT NOT NULL,
  api_key_encrypted TEXT NOT NULL,
  input_cost_per_million NUMERIC(14,6) NOT NULL DEFAULT 0,
  output_cost_per_million NUMERIC(14,6) NOT NULL DEFAULT 0,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS workspace_providers_tenant_idx ON workspace_providers(tenant_id);
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS monthly_budget NUMERIC(14,2) NOT NULL DEFAULT 100;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS rate_limit_per_minute INTEGER NOT NULL DEFAULT 60;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS max_retries INTEGER NOT NULL DEFAULT 1;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS timeout_seconds INTEGER NOT NULL DEFAULT 30;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS alerts_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS budget_alert_percent INTEGER NOT NULL DEFAULT 80;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS latency_alert_ms INTEGER NOT NULL DEFAULT 5000;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS cache_hit_alert_percent INTEGER NOT NULL DEFAULT 20;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS webhook_url_encrypted TEXT;
CREATE TABLE IF NOT EXISTS notifications(id BIGSERIAL PRIMARY KEY,tenant_id TEXT NOT NULL REFERENCES workspaces(tenant_id) ON DELETE CASCADE,kind TEXT NOT NULL,title TEXT NOT NULL,message TEXT NOT NULL,severity TEXT NOT NULL DEFAULT 'info',read_at TIMESTAMPTZ,created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS notifications_tenant_idx ON notifications(tenant_id,id DESC);

ALTER TABLE users ADD COLUMN IF NOT EXISTS plan TEXT NOT NULL DEFAULT 'developer';
ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_status TEXT NOT NULL DEFAULT 'free';
ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_subscription_id TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS current_period_end TIMESTAMPTZ;
