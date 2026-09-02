import hashlib, hmac, json, os, time, unittest
from unittest.mock import patch
from fastapi import HTTPException
from promptcache.production import billing

class BillingTests(unittest.TestCase):
    def test_plan_limits_are_ordered(self):
        self.assertEqual(billing.PLANS['developer']['requests'], 10_000)
        self.assertGreater(billing.PLANS['growth']['requests'], billing.PLANS['startup']['requests'])

    def test_request_limit_rejects_exhausted_plan(self):
        class Result:
            def first(self): return (12,)
        class Session:
            def execute(self, *_args, **_kwargs): return Result()
        with patch.object(billing, 'billing_summary', return_value={'requests_used': 10, 'requests_limit': 10}):
            with self.assertRaises(HTTPException) as raised: billing.enforce_request_limit(Session(), 'ws_test')
        self.assertEqual(raised.exception.status_code, 402)

    def test_signed_webhook_is_verified(self):
        payload=json.dumps({'id':'evt_test'}).encode(); timestamp=str(int(time.time())); secret='whsec_test'
        signature=hmac.new(secret.encode(),timestamp.encode()+b'.'+payload,hashlib.sha256).hexdigest()
        with patch.dict(os.environ,{'STRIPE_WEBHOOK_SECRET':secret}):
            self.assertEqual(billing.verify_webhook(payload,f't={timestamp},v1={signature}')['id'],'evt_test')

    def test_bad_signature_is_rejected(self):
        with patch.dict(os.environ,{'STRIPE_WEBHOOK_SECRET':'whsec_test'}):
            with self.assertRaises(HTTPException): billing.verify_webhook(b'{}',f't={int(time.time())},v1=bad')

def test_workspace_limit_message_includes_plan(self):
        summary = {"plan_name": "Developer", "workspaces_used": 1, "workspaces_limit": 1}
        with patch.object(billing, "billing_summary", return_value=summary):
            with self.assertRaises(HTTPException) as raised:
                billing.enforce_workspace_limit(object(), 1)
        self.assertEqual(raised.exception.status_code, 402)
        self.assertIn("Developer", raised.exception.detail)
        self.assertIn("workspace", raised.exception.detail.lower())
if __name__ == '__main__': unittest.main()
