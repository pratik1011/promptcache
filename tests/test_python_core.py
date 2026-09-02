import tempfile
import unittest
from promptcache.cache.semantic import normalize_prompt, similarity
from promptcache.db.store import Store
from promptcache.config.settings import Settings
from promptcache.core.gateway import complete

class CoreTests(unittest.TestCase):
 def test_cache_and_similarity(self):
  self.assertEqual(normalize_prompt([{"role":"user","content":"Hello, WORLD!"}]),"user:hello world")
  self.assertGreater(similarity("summarize quarterly sales report","please summarize the quarterly sales report"),.85)
 def test_gateway_hit(self):
  with tempfile.TemporaryDirectory() as d:
   p={"id":"demo","type":"generic","baseUrl":"mock://local","model":"demo","inputCostPerMillion":1,"outputCostPerMillion":2};s=Settings(8787,"development-only",.92,86400,[p],[{"maxComplexity":10,"provider":"demo"}],d+"/db.json");store=Store(s.data_file);body={"messages":[{"role":"user","content":"Summarize refunds"}]};self.assertFalse(complete(body,s,store)["promptcache"]["cached"]);self.assertTrue(complete(body,s,store)["promptcache"]["cached"])
 def test_sensitive_prompts_are_not_cached(self):
  with tempfile.TemporaryDirectory() as d:
   p={"id":"demo","type":"generic","baseUrl":"mock://local","model":"demo","inputCostPerMillion":1,"outputCostPerMillion":2};s=Settings(8787,"development-only",.92,86400,[p],[{"maxComplexity":10,"provider":"demo"}],d+"/db.json");store=Store(s.data_file)
   for secret in ("password: hunter2","api_key: abc123def","card number: 4111111111111111","Bearer abcdefghijklmnop"):
    body={"messages":[{"role":"user","content":f"please remember {secret}"}]}
    first=complete(body,s,store);second=complete(body,s,store)
    self.assertFalse(first["promptcache"]["cached"]);self.assertFalse(second["promptcache"]["cached"])
   self.assertEqual(store.state["cache"],[])

