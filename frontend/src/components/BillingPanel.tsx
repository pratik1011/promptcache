import { useEffect, useState } from 'react'
import { createBillingCheckout, createBillingPortal, fetchBilling } from '../lib/api'
import type { BillingSummary } from '../types'

export default function BillingPanel({ token }: { token: string }) {
  const [billing, setBilling] = useState<BillingSummary | null>(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  useEffect(() => { void fetchBilling(token).then(setBilling).catch((e) => setError(e.message)) }, [token])
  const checkout = async (plan: string) => {
    setBusy(plan); setError('')
    try { window.location.href = await createBillingCheckout(token, plan) }
    catch (e) { setError(e instanceof Error ? e.message : 'Checkout unavailable') }
    finally { setBusy('') }
  }
  const portal = async () => {
    setBusy('portal'); setError('')
    try { window.location.href = await createBillingPortal(token) }
    catch (e) { setError(e instanceof Error ? e.message : 'Billing portal unavailable') }
    finally { setBusy('') }
  }
  if (!billing) return <article className='panel billing-panel'><h2>Plan & billing</h2><p>{error || 'Loading billing details…'}</p></article>
  const percent = Math.min(100, billing.requests_used / billing.requests_limit * 100)
  return <article className='panel billing-panel'>
    <div className='panel-head'><div><h2>Plan & billing</h2><p>Manage usage and your subscription.</p></div><span className='plan-pill'>{billing.plan_name}</span></div>
    <div className='usage-line'><span>Monthly requests</span><b>{billing.requests_used.toLocaleString()} / {billing.requests_limit.toLocaleString()}</b></div>
    <div className='billing-progress'><i style={{ width: `${percent}%` }} /></div>
    <div className='usage-line'><span>Workspaces</span><b>{billing.workspaces_used} / {billing.workspaces_limit}</b></div>
    {error && <p className='billing-error'>{error}</p>}
    <div className='plan-grid'>{billing.plans.filter((p) => p.id !== 'developer').map((plan) => <div className={billing.plan === plan.id ? 'current' : ''} key={plan.id}><b>{plan.name}</b><strong>${plan.price}<small>/mo</small></strong><span>{plan.requests.toLocaleString()} requests</span><button disabled={!plan.configured || billing.plan === plan.id || Boolean(busy)} onClick={() => void checkout(plan.id)}>{billing.plan === plan.id ? 'Current plan' : !plan.configured ? 'Coming soon' : busy === plan.id ? 'Opening…' : 'Upgrade'}</button></div>)}</div>
    {billing.has_billing_account && <button className='portal-button' disabled={Boolean(busy)} onClick={() => void portal()}>Manage billing & invoices</button>}
  </article>
}
