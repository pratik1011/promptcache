'''Stripe billing and plan enforcement for PromptCache.'''
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone

import httpx
import jwt
from fastapi import HTTPException
from sqlalchemy import text

from .config import jwt_secret

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

def billing_summary(session, user_id: int) -> dict:
    user = session.execute(text('''SELECT email, plan, subscription_status,
        stripe_customer_id, current_period_end FROM users WHERE id=:id'''), {'id': user_id}).mappings().first()
    if not user:
        raise HTTPException(404, 'User not found')
    plan_id = user['plan'] if user['plan'] in PLANS else 'developer'
    plan = PLANS[plan_id]
    now = datetime.now(timezone.utc)
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
            period_dt = datetime.fromtimestamp(period, timezone.utc) if period else None
            session.execute(text('''UPDATE users SET plan=:plan, subscription_status=:status,
                stripe_customer_id=:customer, stripe_subscription_id=:subscription,
                current_period_end=:period WHERE id=:id'''), {'plan': plan, 'status': status,
                'customer': obj.get('customer'), 'subscription': obj.get('id'), 'period': period_dt, 'id': int(user_id)})
    session.commit()
