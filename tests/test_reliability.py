import unittest
from unittest.mock import MagicMock,patch
from fastapi import HTTPException
from promptcache.production import reliability
from promptcache.production.rate_limit import RateLimitExceeded,RateLimiter

class ReliabilityTests(unittest.TestCase):
 def test_budget_rejects_spend_at_limit(self):
  with patch.object(reliability,'get_policy',return_value={'monthly_budget':10,'spent_this_month':10}):
   with self.assertRaises(HTTPException) as raised:reliability.enforce_budget(object(),'ws')
  self.assertEqual(raised.exception.status_code,402)
 def test_zero_budget_means_uncapped(self):
  with patch.object(reliability,'get_policy',return_value={'monthly_budget':0,'spent_this_month':999}):
   self.assertEqual(reliability.enforce_budget(object(),'ws')['monthly_budget'],0)
 def test_missing_workspace_row_includes_spend_keys(self):
  '''Bootstrap tenants have an api_key but no workspaces row; the policy must
  still carry spent_this_month/remaining_budget or enforce_budget KeyErrors.'''
  from sqlalchemy import create_engine,text
  from sqlalchemy.orm import Session
  engine=create_engine('sqlite://')
  with engine.begin() as conn:
   conn.execute(text('CREATE TABLE workspaces (id INTEGER PRIMARY KEY, tenant_id TEXT, monthly_budget NUMERIC, rate_limit_per_minute INTEGER, max_retries INTEGER, timeout_seconds INTEGER)'))
  with Session(engine) as session:
   policy=reliability.enforce_budget(session,'ghost-tenant')
  self.assertEqual(policy['spent_this_month'],0.0)
  self.assertEqual(policy['remaining_budget'],100.0)
  self.assertEqual(policy['monthly_budget'],100.0)
 def test_dynamic_rate_limit_overrides_default(self):
  limiter=RateLimiter(limit=100);limiter.client=MagicMock();pipe=MagicMock();pipe.execute.return_value=(6,30);pipe.__enter__.return_value=pipe;limiter.client.pipeline.return_value=pipe
  with self.assertRaises(RateLimitExceeded):limiter.check('ws',5)
 def test_dynamic_rate_limit_allows_request(self):
  limiter=RateLimiter(limit=1);limiter.client=MagicMock();pipe=MagicMock();pipe.execute.return_value=(5,30);pipe.__enter__.return_value=pipe;limiter.client.pipeline.return_value=pipe
  limiter.check('ws',5)
if __name__=='__main__':unittest.main()
