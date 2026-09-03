'''Stripe billing and plan enforcement for PromptCache.'''
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, UTC

import httpx
import jwt
from fastapi import HTTPException
from sqlalchemy import text

from .config import jwt_secret

logger = logging.getLogger("promptcache")

PLANS = {
    'developer': {'name': 'Developer', 'price': 0, 'requests': 10_000, 'workspaces': 1},
    'startup': {'name': 'Startup', 'price': 39, 'requests': 100_000, 'workspaces': 3},
    'growth': {'name': 'Growth', 'price': 99, 'requests': 1_000_000, 'workspaces': 10},
    'scale': {'name': 'Scale', 'price': 299, 'requests': 5_000_000, 'workspaces': 50},
}

def user_id_from_token(authorization: str | None) -> int:
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Bearer token required')
    try:
        payload = jwt.decode(authorization.removeprefix('Bearer ').strip(), jwt_secret(), algorithms=['HS256'])
        return int(payload['sub'])
    except Exception as exc:
        raise HTTPException(401, 'Invalid or expired token') from exc

def stripe_enabled() -> bool:
    return bool(os.getenv('STRIPE_SECRET_KEY'))

def price_id(plan: str) -> str:
    return os.getenv(f'STRIPE_PRICE_{plan.upper()}', '')

def savings_fee_summary(session, user_id: int) -> dict:
    """Usage-based pricing: a share of verified monthly savings as the platform fee.

    SAVINGS_SHARE_PERCENT sets the percentage (0 disables the fee);
    PLATFORM_FEE_CAP optionally ceilings the monthly charge in USD.
    """
    share = float(os.getenv('SAVINGS_SHARE_PERCENT', '10') or 0)
    cap = float(os.getenv('PLATFORM_FEE_CAP', '0') or 0)
    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    saved = session.execute(text('''SELECT coalesce(sum(e.saved),0) FROM usage_events e JOIN workspaces w
        ON w.tenant_id=e.tenant_id WHERE w.owner_id=:id AND e.created_at >= :month_start'''),
        {'id': user_id, 'month_start': month_start}).scalar() or 0
    fee = float(saved) * share / 100.0
    if cap > 0:
        fee = min(fee, cap)
    now_dt = now
    month = now_dt.strftime('%Y-%m')
    accrued = _accrued_total(session, user_id, month)
    return {'savings_this_month': float(saved), 'savings_share_percent': share,
            'platform_fee': round(fee, 2), 'platform_fee_cap': cap or None,
            'month': month, 'accrued_this_month': accrued,
            'unbilled_fee': round(max(0.0, fee - accrued), 2)}

def _accrued_total(session, user_id: int, month: str) -> float:
    """Accrued-so-far total from the fee ledger; 0.0 when the table is absent
    (pre-migration databases) so the billing read path can never 500."""
    try:
        row = session.execute(text('SELECT accrued FROM fee_accruals WHERE user_id=:u AND month=:m'),
                              {'u': user_id, 'm': month}).first()
        return float(row[0]) if row else 0.0
    except Exception:
        session.rollback()
        return 0.0

def accrue_savings_fee(session, user_id: int) -> dict:
    """Bill the unbilled share of this month's savings fee via a Stripe invoice item.

    Stripe adds the item to the customer's next subscription invoice. The
    fee_accruals ledger makes accrual idempotent: only the unbilled delta
    (fee minus already-accrued) is invoiced, and deltas below one cent are
    skipped because Stripe rejects sub-cent invoice items. Without Stripe
    configured, or without a Stripe customer, nothing is billed or recorded â€”
    so dev environments stay no-op and the first real accrual bills in full.
    A shrinking fee (credit scenario) is ignored rather than netted.
    """
    summary = savings_fee_summary(session, user_id)
    unbilled = round(summary['platform_fee'] - summary['accrued_this_month'], 2)
    result = {**summary, 'billed_now': 0.0, 'invoice_item_id': None, 'accrued': False}
    if unbilled < 0.01:
        return result
    if not stripe_enabled():
        return {**result, 'reason': 'stripe_not_configured'}
    customer = session.execute(text('SELECT stripe_customer_id FROM users WHERE id=:id'), {'id': user_id}).scalar()
    if not customer:
        return {**result, 'reason': 'no_billing_account'}
    item = _stripe_post('invoiceitems', {
        'customer': customer, 'amount': int(round(unbilled * 100)), 'currency': 'usd',
        'description': f"PromptCache platform fee ({summary['savings_share_percent']:g}% of ${summary['savings_this_month']:.2f} saved)"})
    now = datetime.now(UTC)
    # ON CONFLICT works on both Postgres and SQLite (3.24+); a ledger write
    # failure raises, which prevents billing without recording the accrual.
    session.execute(text('''INSERT INTO fee_accruals (user_id, month, accrued, currency, last_accrued_at)
        VALUES (:u, :m, :a, 'usd', :at)
        ON CONFLICT (user_id, month) DO UPDATE SET accrued=:a, last_accrued_at=:at'''),
        {'u': user_id, 'm': summary['month'], 'a': summary['platform_fee'], 'at': now})
    session.commit()
    return {**result, 'billed_now': unbilled, 'invoice_item_id': item.get('id'), 'accrued': True}

def accrue_all_fees(session) -> dict:
    """Accrue the savings fee for every user with a Stripe billing account.

    Entry point for the daily fee cron (POST /v1/admin/accrue-fees); one
    failing user is logged and skipped instead of blocking the rest.
    """
    if not stripe_enabled():
        return {'scanned': 0, 'billed_users': 0, 'billed_total': 0.0, 'skipped': 'stripe_not_configured'}
    ids = [int(row[0]) for row in session.execute(
        text('SELECT id FROM users WHERE stripe_customer_id IS NOT NULL')).all()]
    results = []
    for user_id in ids:
        try:
            results.append(accrue_savings_fee(session, user_id))
        except Exception as exc:
            session.rollback()
            logger.warning('savings-fee accrual failed for user %s: %s', user_id, exc)
    return {'scanned': len(ids),
            'billed_users': sum(1 for r in results if r.get('accrued')),
            'billed_total': round(sum(float(r.get('billed_now') or 0) for r in results), 2)}

def billing_summary(session, user_id: int) -> dict:
    user = session.execute(text('''SELECT email, plan, subscription_status,
        stripe_customer_id, current_period_end FROM users WHERE id=:id'''), {'id': user_id}).mappings().first()
    if not user:
        raise HTTPException(404, 'User not found')
    plan_id = user['plan'] if user['plan'] in PLANS else 'developer'
    plan = PLANS[plan_id]
    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    usage = session.execute(text('''SELECT count(*) FROM usage_events e JOIN workspaces w
        ON w.tenant_id=e.tenant_id WHERE w.owner_id=:id
        AND e.created_at >= :month_start'''), {'id': user_id, 'month_start': month_start}).scalar() or 0
    workspace_count = session.execute(text('SELECT count(*) FROM workspaces WHERE owner_id=:id'), {'id': user_id}).scalar() or 0
    return {
        'plan': plan_id, 'plan_name': plan['name'], 'status': user['subscription_status'] or 'free',
        'requests_used': usage, 'requests_limit': plan['requests'],
        'workspaces_used': workspace_count, 'workspaces_limit': plan['workspaces'],
        'current_period_end': user['current_period_end'].isoformat() if user['current_period_end'] else None,
        'stripe_enabled': stripe_enabled(), 'has_billing_account': bool(user['stripe_customer_id']),
        'savings_fee': savings_fee_summary(session, user_id),
        'plans': [{**value, 'id': key, 'configured': key == 'developer' or bool(price_id(key))} for key, value in PLANS.items()],
    }

def enforce_workspace_limit(session, user_id: int) -> None:
    summary = billing_summary(session, user_id)
    if summary['workspaces_used'] >= summary['workspaces_limit']:
        raise HTTPException(402, f"{summary['plan_name']} allows {summary['workspaces_limit']} workspace(s). Upgrade to create another.")

def enforce_request_limit(session, tenant_id: str) -> None:
    row = session.execute(text('SELECT owner_id FROM workspaces WHERE tenant_id=:t'), {'t': tenant_id}).first()
    if not row:
        return
    summary = billing_summary(session, int(row[0]))
    if summary['requests_used'] >= summary['requests_limit']:
        raise HTTPException(402, 'Monthly request limit reached. Upgrade your plan to continue.')

def _stripe_post(path: str, values: dict) -> dict:
    secret = os.getenv('STRIPE_SECRET_KEY', '')
    if not secret:
        raise HTTPException(503, 'Billing is not configured yet')
    response = httpx.post(f'https://api.stripe.com/v1/{path}', data=values, auth=(secret, ''), timeout=20)
    if response.is_error:
        detail = response.json().get('error', {}).get('message', 'Stripe request failed')
        raise HTTPException(502, detail)
    return response.json()

def checkout(session, user_id: int, plan: str) -> str:
    if plan not in PLANS or plan == 'developer' or not price_id(plan):
        raise HTTPException(400, 'This plan is not available for checkout')
    user = session.execute(text('SELECT email, stripe_customer_id FROM users WHERE id=:id'), {'id': user_id}).mappings().first()
    origin = os.getenv('DASHBOARD_URL', 'http://127.0.0.1:5173')
    values = {'mode': 'subscription', 'line_items[0][price]': price_id(plan), 'line_items[0][quantity]': 1,
              'success_url': f'{origin}/?checkout=success', 'cancel_url': f'{origin}/?checkout=cancelled',
              'client_reference_id': str(user_id), 'metadata[user_id]': str(user_id), 'metadata[plan]': plan,
              'subscription_data[metadata][user_id]': str(user_id), 'subscription_data[metadata][plan]': plan}
    if user['stripe_customer_id']:
        values['customer'] = user['stripe_customer_id']
    else:
        values['customer_email'] = user['email']
    return _stripe_post('checkout/sessions', values)['url']

def portal(session, user_id: int) -> str:
    customer = session.execute(text('SELECT stripe_customer_id FROM users WHERE id=:id'), {'id': user_id}).scalar()
    if not customer:
        raise HTTPException(400, 'No billing account exists yet')
    origin = os.getenv('DASHBOARD_URL', 'http://127.0.0.1:5173')
    return _stripe_post('billing_portal/sessions', {'customer': customer, 'return_url': origin})['url']

def verify_webhook(payload: bytes, signature: str) -> dict:
    secret = os.getenv('STRIPE_WEBHOOK_SECRET', '')
    if not secret:
        raise HTTPException(503, 'Stripe webhook is not configured')
    parts = dict(item.split('=', 1) for item in signature.split(',') if '=' in item)
    timestamp = parts.get('t', '')
    expected = hmac.new(secret.encode(), timestamp.encode() + b'.' + payload, hashlib.sha256).hexdigest()
    if not timestamp or abs(time.time() - int(timestamp)) > 300 or not hmac.compare_digest(expected, parts.get('v1', '')):
        raise HTTPException(400, 'Invalid webhook signature')
    return json.loads(payload)

def apply_event(session, event: dict) -> None:
    obj = event.get('data', {}).get('object', {})
    event_type = event.get('type', '')
    metadata = obj.get('metadata', {})
    user_id = metadata.get('user_id') or obj.get('client_reference_id')
    if event_type == 'checkout.session.completed' and user_id:
        session.execute(text('''UPDATE users SET stripe_customer_id=:customer,
            stripe_subscription_id=:subscription WHERE id=:id'''),
            {'customer': obj.get('customer'), 'subscription': obj.get('subscription'), 'id': int(user_id)})
    elif event_type.startswith('customer.subscription.'):
        if not user_id:
            row = session.execute(text('SELECT id FROM users WHERE stripe_customer_id=:c'), {'c': obj.get('customer')}).first()
            user_id = row[0] if row else None
        if user_id:
            status = obj.get('status', 'inactive')
            plan = metadata.get('plan', 'developer') if status in ('active', 'trialing') else 'developer'
            period = obj.get('current_period_end')
            period_dt = datetime.fromtimestamp(period, UTC) if period else None
            session.execute(text('''UPDATE users SET plan=:plan, subscription_status=:status,
                stripe_customer_id=:customer, stripe_subscription_id=:subscription,
                current_period_end=:period WHERE id=:id'''), {'plan': plan, 'status': status,
                'customer': obj.get('customer'), 'subscription': obj.get('id'), 'period': period_dt, 'id': int(user_id)})
    session.commit()
