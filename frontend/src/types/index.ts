export type NoticeType = 'success' | 'error' | 'info'
export type Notice = { type: NoticeType; message: string } | null

export type Provider = {
  id: string
  type: string
  model: string
}

export type Metrics = {
  requests: number
  saved: number
  actual_cost: number
  cache_hit_rate: number
  baseline_cost?: number
  cache_hits?: number
  by_provider?: { provider: string; requests: number; actual_cost: number; saved: number }[]
  by_day?: { date: string; requests: number; actual_cost: number; saved: number }[]
}

export type Workspace = {
  name: string
  tenant_id: string
}

export type UserInfo = {
  email: string
  workspaces: Workspace[]
}

export type AuthState = {
  token: string | null
  user: UserInfo | null
  loading: 'signup' | 'login' | 'metrics' | 'profile' | null
  notice: Notice
}

export type KeyInfo = {
  id: number
  active: boolean
  created_at: string | null
  expires_at: string | null
  days_remaining: number | null
  expired: boolean
}

export type RevealedKey = {
  id: number
  key: string
  created_at: string | null
  expires_at: string | null
}

export type BillingPlan = { id: string; name: string; price: number; requests: number; workspaces: number; configured: boolean }
export type BillingSummary = { plan: string; plan_name: string; status: string; requests_used: number; requests_limit: number; workspaces_used: number; workspaces_limit: number; current_period_end: string | null; stripe_enabled: boolean; has_billing_account: boolean; plans: BillingPlan[] }
export type RequestEvent = { id: number; provider: string; cached: boolean; actual_cost: number; baseline_cost: number; saved: number; latency_ms: number; created_at: string | null }
export type RequestLedger = { tenant_id: string; items: RequestEvent[]; next_cursor: number | null }
export type ProviderPreset = { id: string; name: string; base_url: string; model: string }
export type ProviderConnection = { id: number; provider_type: string; name: string; base_url: string; model: string; input_cost_per_million: number; output_cost_per_million: number; active: boolean; created_at: string | null }
export type ReliabilityPolicy = { monthly_budget: number; spent_this_month: number; remaining_budget: number; rate_limit_per_minute: number; max_retries: number; timeout_seconds: number }
export type AlertSettings = { enabled: boolean; budget_percent: number; latency_ms: number; cache_hit_percent: number; webhook_configured: boolean }
export type Notification = { id: number; kind: string; title: string; message: string; severity: string; read: boolean; read_at: string | null; created_at: string | null }
export type ActivationStep = { id: string; label: string; detail: string; complete: boolean }
export type ActivationStatus = { tenant_id: string; steps: ActivationStep[]; completed: number; total: number; requests: number; cache_hits: number }
export type AuditEvent = { id: number; tenant_id: string; user_id: number | null; action: string; target: string; detail: Record<string, unknown>; created_at: string | null }
