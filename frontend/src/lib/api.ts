import type { ActivationStatus, AlertSettings, AuditEvent, BillingSummary, Metrics, Notification, ProviderConnection, ProviderPreset, ReliabilityPolicy, RequestLedger, UserInfo, RevealedKey } from '../types'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8787'

export const money = (v: number) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 4 }).format(v || 0)

export async function signup(email: string, password: string): Promise<{ access_token: string; token_type: string; expires_in: number; message: string }> {
  const r = await fetch(`${API_URL}/v1/auth/signup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (!r.ok) {
    const err = await r.json().catch(() => ({}))
    throw new Error(err.detail || 'Unable to create account')
  }
  return r.json()
}

export async function createWorkspace(token: string, name: string): Promise<{ tenant_id: string; name: string; api_key: string; expires_at: string; message: string }> {
  const r = await fetch(`${API_URL}/v1/workspaces`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ name }),
  })
  if (!r.ok) {
    const err = await r.json().catch(() => ({}))
    throw new Error(err.detail || 'Unable to create workspace')
  }
  return r.json()
}

export async function login(email: string, password: string): Promise<{ access_token: string; token_type: string; expires_in: number }> {
  const r = await fetch(`${API_URL}/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (!r.ok) throw new Error('Invalid email or password')
  return r.json()
}

export async function fetchMe(token: string): Promise<UserInfo> {
  const r = await fetch(`${API_URL}/v1/me`, { headers: { Authorization: `Bearer ${token}` } })
  if (!r.ok) throw new Error('Session expired')
  return r.json()
}

export async function regenerateKey(token: string, tenantId: string): Promise<{ tenant_id: string; api_key: string; expires_at: string; message: string }> {
  const r = await fetch(`${API_URL}/v1/workspaces/${tenantId}/regenerate-key`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
  })
  if (!r.ok) {
    const err = await r.json().catch(() => ({}))
    throw new Error(err.detail || 'Unable to regenerate key')
  }
  return r.json()
}

export async function fetchWorkspaceKeys(token: string, tenantId: string): Promise<{ tenant_id: string; keys: KeyInfo[] }> {
  const r = await fetch(`${API_URL}/v1/workspaces/${tenantId}/keys`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!r.ok) {
    const err = await r.json().catch(() => ({}))
    throw new Error(err.detail || 'Unable to fetch keys')
  }
  return r.json()
}

export async function revealWorkspaceKeys(token: string, tenantId: string): Promise<{ tenant_id: string; keys: RevealedKey[] }> {
  const r = await fetch(`${API_URL}/v1/workspaces/${tenantId}/keys/reveal`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!r.ok) {
    const err = await r.json().catch(() => ({}))
    throw new Error(err.detail || 'Unable to reveal keys')
  }
  return r.json()
}

export async function fetchMetrics(token: string): Promise<Metrics> {
  const r = await fetch(`${API_URL}/v1/metrics`, { headers: { Authorization: `Bearer ${token}` } })
  if (!r.ok) throw new Error('Invalid tenant API key')
  return r.json()
}

export async function fetchProviders(): Promise<{id: string; type: string; model: string}[]> {
  const r = await fetch(`${API_URL}/health`)
  if (!r.ok) throw new Error('Unable to fetch provider catalog')
  const data = await r.json()
  return (data.providers || []).map((p: {id: string; type?: string; model?: string}) => ({id: p.id, type: p.type || '', model: p.model || ''}))
}

export async function fetchBaseline(token: string, tenantId: string): Promise<{tenant_id: string; baseline_provider: string | null}> {
  const r = await fetch(`${API_URL}/v1/workspaces/${tenantId}/baseline`, { headers: { Authorization: `Bearer ${token}` } })
  if (r.status === 404) return {tenant_id: tenantId, baseline_provider: null}
  if (!r.ok) throw new Error('Unable to fetch baseline')
  return r.json()
}

export async function setBaseline(token: string, tenantId: string, provider: string): Promise<{tenant_id: string; baseline_provider: string; message: string}> {
  const r = await fetch(`${API_URL}/v1/workspaces/${tenantId}/baseline`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ provider }),
  })
  if (!r.ok) throw new Error(r.status === 400 ? 'Unknown provider' : 'Unable to set baseline')
  return r.json()
}

export type KeyInfo = {
  id: number
  active: boolean
  created_at: string | null
  expires_at: string | null
  days_remaining: number | null
  expired: boolean
}

export async function changePassword(token:string,currentPassword:string,newPassword:string):Promise<void>{const r=await fetch(`${API_URL}/v1/auth/change-password`,{method:'POST',headers:{'Content-Type':'application/json',Authorization:`Bearer ${token}`},body:JSON.stringify({current_password:currentPassword,new_password:newPassword})});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||'Unable to change password')}
export async function exportAccount(token:string):Promise<unknown>{const r=await fetch(`${API_URL}/v1/account/export`,{headers:{Authorization:`Bearer ${token}`}});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||'Unable to export account');return d}

export async function fetchBilling(token: string): Promise<BillingSummary> {
  const r = await fetch(`${API_URL}/v1/billing`, { headers: { Authorization: `Bearer ${token}` } })
  if (!r.ok) throw new Error('Unable to load billing')
  return r.json()
}

export async function createBillingCheckout(token: string, plan: string): Promise<string> {
  const r = await fetch(`${API_URL}/v1/billing/checkout`, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify({ plan }) })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.detail || 'Checkout unavailable')
  return data.url
}

export async function createBillingPortal(token: string): Promise<string> {
  const r = await fetch(`${API_URL}/v1/billing/portal`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.detail || 'Billing portal unavailable')
  return data.url
}

export async function fetchRequestLedger(token: string, tenantId: string, beforeId: number | null = null): Promise<RequestLedger> {
  const query = beforeId ? `?limit=50&before_id=${beforeId}` : '?limit=50'
  const r = await fetch(`${API_URL}/v1/workspaces/${tenantId}/requests${query}`, { headers: { Authorization: `Bearer ${token}` } })
  if (!r.ok) throw new Error('Unable to load request activity')
  return r.json()
}

export type ProviderInput = { provider_type: string; name?: string; api_key: string; base_url?: string; model?: string; input_cost_per_million: number; output_cost_per_million: number }
export async function fetchProviderPresets(): Promise<ProviderPreset[]> { const r=await fetch(`${API_URL}/v1/provider-presets`);if(!r.ok)throw new Error('Unable to load providers');return r.json() }
export async function fetchWorkspaceProviders(token:string,tenantId:string):Promise<ProviderConnection[]>{const r=await fetch(`${API_URL}/v1/workspaces/${tenantId}/providers`,{headers:{Authorization:`Bearer ${token}`}});if(!r.ok)throw new Error('Unable to load connections');return (await r.json()).providers}
export async function testProvider(token:string,tenantId:string,input:ProviderInput):Promise<void>{const r=await fetch(`${API_URL}/v1/workspaces/${tenantId}/providers/test`,{method:'POST',headers:{'Content-Type':'application/json',Authorization:`Bearer ${token}`},body:JSON.stringify(input)});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||'Connection failed')}
export async function connectProvider(token:string,tenantId:string,input:ProviderInput):Promise<ProviderConnection>{const r=await fetch(`${API_URL}/v1/workspaces/${tenantId}/providers`,{method:'POST',headers:{'Content-Type':'application/json',Authorization:`Bearer ${token}`},body:JSON.stringify(input)});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||'Unable to save provider');return d}
export async function disconnectProvider(token:string,tenantId:string,id:number):Promise<void>{const r=await fetch(`${API_URL}/v1/workspaces/${tenantId}/providers/${id}`,{method:'DELETE',headers:{Authorization:`Bearer ${token}`}});if(!r.ok)throw new Error('Unable to remove provider')}
export async function sendTestRequest(apiKey:string):Promise<{cached:boolean;provider:string}>{const r=await fetch(`${API_URL}/v1/chat/completions`,{method:'POST',headers:{'Content-Type':'application/json',Authorization:`Bearer ${apiKey}`},body:JSON.stringify({messages:[{role:'user',content:'Reply with: PromptCache is connected.'}]})});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||'Test request failed');return d.promptcache}
export async function fetchReliability(token:string,tenantId:string):Promise<ReliabilityPolicy>{const r=await fetch(`${API_URL}/v1/workspaces/${tenantId}/reliability`,{headers:{Authorization:`Bearer ${token}`}});if(!r.ok)throw new Error('Unable to load reliability policy');return r.json()}
export async function saveReliability(token:string,tenantId:string,policy:Omit<ReliabilityPolicy,'spent_this_month'|'remaining_budget'>):Promise<ReliabilityPolicy>{const r=await fetch(`${API_URL}/v1/workspaces/${tenantId}/reliability`,{method:'PUT',headers:{'Content-Type':'application/json',Authorization:`Bearer ${token}`},body:JSON.stringify(policy)});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||'Unable to save reliability policy');return d}
export async function fetchAlertSettings(token:string,tenantId:string):Promise<AlertSettings>{const r=await fetch(`${API_URL}/v1/workspaces/${tenantId}/alerts`,{headers:{Authorization:`Bearer ${token}`}});if(!r.ok)throw new Error('Unable to load alert settings');return r.json()}
export async function saveAlertSettings(token:string,tenantId:string,settings:AlertSettings&{webhook_url?:string}):Promise<AlertSettings>{const r=await fetch(`${API_URL}/v1/workspaces/${tenantId}/alerts`,{method:'PUT',headers:{'Content-Type':'application/json',Authorization:`Bearer ${token}`},body:JSON.stringify(settings)});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||'Unable to save alerts');return d}
export async function fetchNotifications(token:string,tenantId:string):Promise<Notification[]>{const r=await fetch(`${API_URL}/v1/workspaces/${tenantId}/notifications`,{headers:{Authorization:`Bearer ${token}`}});if(!r.ok)throw new Error('Unable to load notifications');return (await r.json()).notifications}
export async function markNotificationRead(token:string,tenantId:string,id:number):Promise<void>{const r=await fetch(`${API_URL}/v1/workspaces/${tenantId}/notifications/${id}/read`,{method:'POST',headers:{Authorization:`Bearer ${token}`}});if(!r.ok)throw new Error('Unable to update notification')}
export async function fetchActivation(token:string,tenantId:string):Promise<ActivationStatus>{const r=await fetch(`${API_URL}/v1/workspaces/${tenantId}/activation`,{headers:{Authorization:`Bearer ${token}`}});if(!r.ok)throw new Error('Unable to load activation status');return r.json()}
export async function fetchAuditEvents(token:string,tenantId:string):Promise<AuditEvent[]>{const r=await fetch(`${API_URL}/v1/workspaces/${tenantId}/audit?limit=100`,{headers:{Authorization:`Bearer ${token}`}});if(!r.ok)throw new Error('Unable to load audit history');return (await r.json()).events}
