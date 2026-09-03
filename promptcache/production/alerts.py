'''Workspace alert policies and in-app notifications.'''
import ipaddress
import socket
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,UTC
from urllib.parse import urlparse
import httpx
from sqlalchemy import text
from .auth import decrypt_key,encrypt_key
from .reliability import get_policy

logger=logging.getLogger("promptcache")
# Webhook delivery runs off the request path; a slow upstream must never block a gateway request.
_WEBHOOK_EXECUTOR=ThreadPoolExecutor(max_workers=4,thread_name_prefix="pc-alert-webhook")

def _safe_webhook(url:str)->bool:
 try:
  parsed=urlparse(url)
  if parsed.scheme!='https' or not parsed.hostname:return False
  return all(not ipaddress.ip_address(item[4][0]).is_private for item in socket.getaddrinfo(parsed.hostname,443))
 except Exception:return False

def get_alert_settings(session,tenant_id:str)->dict:
 row=session.execute(text('SELECT alerts_enabled,budget_alert_percent,latency_alert_ms,cache_hit_alert_percent,webhook_url_encrypted FROM workspaces WHERE tenant_id=:tenant'),{'tenant':tenant_id}).mappings().first()
 if not row: raise ValueError('Workspace not found')
 return {'enabled':bool(row['alerts_enabled']),'budget_percent':int(row['budget_alert_percent']),'latency_ms':int(row['latency_alert_ms']),'cache_hit_percent':int(row['cache_hit_alert_percent']),'webhook_configured':bool(row['webhook_url_encrypted'])}

def save_alert_settings(session,tenant_id:str,values:dict)->dict:
 webhook=values.get('webhook_url','').strip();encrypted=None
 if webhook:
  if not _safe_webhook(webhook):raise ValueError('Webhook must be a public HTTPS URL')
  encrypted=encrypt_key(webhook)
  if not encrypted: raise ValueError('Webhook encryption is not configured')
 session.execute(text('''UPDATE workspaces SET alerts_enabled=:enabled,budget_alert_percent=:budget,
  latency_alert_ms=:latency,cache_hit_alert_percent=:cache,
  webhook_url_encrypted=coalesce(:webhook,webhook_url_encrypted) WHERE tenant_id=:tenant'''),
  {'enabled':values['enabled'],'budget':values['budget_percent'],'latency':values['latency_ms'],'cache':values['cache_hit_percent'],'webhook':encrypted,'tenant':tenant_id});session.commit();return get_alert_settings(session,tenant_id)

def list_notifications(session,tenant_id:str,limit:int=50)->list[dict]:
 rows=session.execute(text('SELECT id,kind,title,message,severity,read_at,created_at FROM notifications WHERE tenant_id=:tenant ORDER BY id DESC LIMIT :limit'),{'tenant':tenant_id,'limit':limit}).mappings().all()
 return [{**dict(r),'read':bool(r['read_at']),'read_at':r['read_at'].isoformat() if hasattr(r['read_at'],'isoformat') else r['read_at'],'created_at':r['created_at'].isoformat() if hasattr(r['created_at'],'isoformat') else str(r['created_at'])} for r in rows]

def mark_read(session,tenant_id:str,notification_id:int)->bool:
 result=session.execute(text('UPDATE notifications SET read_at=:read_at WHERE id=:id AND tenant_id=:tenant'),{'id':notification_id,'tenant':tenant_id,'read_at':datetime.now(UTC)});session.commit();return result.rowcount==1

def _post_webhook(webhook:str,title:str,message:str)->None:
 try:httpx.post(webhook,json={'text':f'PromptCache — {title}\n{message}'},timeout=3)
 except Exception:
  logger.warning("alert webhook delivery failed for %s",webhook)

def _notify(session,tenant_id:str,kind:str,title:str,message:str,severity:str,webhook:str|None):
 recent=session.execute(text('SELECT 1 FROM notifications WHERE tenant_id=:tenant AND kind=:kind AND created_at>:since'),{'tenant':tenant_id,'kind':kind,'since':datetime.now(UTC)-timedelta(hours=1)}).first()
 if recent:return
 session.execute(text('INSERT INTO notifications(tenant_id,kind,title,message,severity) VALUES (:tenant,:kind,:title,:message,:severity)'),{'tenant':tenant_id,'kind':kind,'title':title,'message':message,'severity':severity});session.commit()
 if webhook:
  try:_WEBHOOK_EXECUTOR.submit(_post_webhook,webhook,title,message)
  except RuntimeError:pass  # interpreter is shutting down

def evaluate_alerts(session,tenant_id:str,latency_ms:int)->None:
 try:
  settings=get_alert_settings(session,tenant_id)
  if not settings['enabled']:return
  encrypted=session.execute(text('SELECT webhook_url_encrypted FROM workspaces WHERE tenant_id=:tenant'),{'tenant':tenant_id}).scalar();webhook=decrypt_key(encrypted) if encrypted else None
  policy=get_policy(session,tenant_id)
  if policy['monthly_budget'] and policy['spent_this_month']/policy['monthly_budget']*100>=settings['budget_percent']:_notify(session,tenant_id,'budget','Budget threshold reached',f"{policy['spent_this_month']:.2f} of {policy['monthly_budget']:.2f} monthly budget used.",'warning',webhook)
  if latency_ms>=settings['latency_ms']:_notify(session,tenant_id,'latency','Slow provider response',f'A request took {latency_ms} ms, above your {settings["latency_ms"]} ms threshold.','warning',webhook)
  count,hits=session.execute(text('SELECT count(*),count(*) FILTER (WHERE cached=true) FROM (SELECT cached FROM usage_events WHERE tenant_id=:tenant ORDER BY id DESC LIMIT 20) recent'),{'tenant':tenant_id}).one()
  if count>=10 and hits/count*100<settings['cache_hit_percent']:_notify(session,tenant_id,'cache','Cache hit rate is low',f'Recent cache hit rate is {hits/count*100:.1f}%, below your {settings["cache_hit_percent"]}% threshold.','info',webhook)
 except Exception:
  session.rollback()
