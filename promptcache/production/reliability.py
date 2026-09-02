'''Workspace reliability, spend, and traffic policies.'''
from fastapi import HTTPException
from sqlalchemy import text
DEFAULTS={'monthly_budget':100.0,'rate_limit_per_minute':60,'max_retries':1,'timeout_seconds':30}
def get_policy(session,tenant_id:str)->dict:
 row=session.execute(text('SELECT monthly_budget,rate_limit_per_minute,max_retries,timeout_seconds FROM workspaces WHERE tenant_id=:tenant'),{'tenant':tenant_id}).mappings().first()
 if not row:return dict(DEFAULTS)
 policy={key:(row[key] if row[key] is not None else value) for key,value in DEFAULTS.items()};policy['monthly_budget']=float(policy['monthly_budget'])
 spent=session.execute(text('SELECT coalesce(sum(actual_cost),0) FROM usage_events WHERE tenant_id=:tenant AND created_at>=date_trunc(\'month\',now())'),{'tenant':tenant_id}).scalar() or 0
 policy['spent_this_month']=float(spent);policy['remaining_budget']=max(0,policy['monthly_budget']-float(spent));return policy
def update_policy(session,tenant_id:str,values:dict)->dict:
 session.execute(text('UPDATE workspaces SET monthly_budget=:budget,rate_limit_per_minute=:rate,max_retries=:retries,timeout_seconds=:timeout WHERE tenant_id=:tenant'),{'budget':values['monthly_budget'],'rate':values['rate_limit_per_minute'],'retries':values['max_retries'],'timeout':values['timeout_seconds'],'tenant':tenant_id});session.commit();return get_policy(session,tenant_id)
def enforce_budget(session,tenant_id:str)->dict:
 policy=get_policy(session,tenant_id)
 if policy['monthly_budget']>0 and policy['spent_this_month']>=policy['monthly_budget']:raise HTTPException(402,'Monthly workspace budget reached. Increase the budget to continue provider requests.')
 return policy
