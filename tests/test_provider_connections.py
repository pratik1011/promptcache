import base64
import os
import secrets
import unittest
from unittest.mock import patch
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from promptcache.production.provider_connections import _complexity_routes, list_connections, runtime_providers, runtime_settings, save_connection

DDL='''CREATE TABLE workspace_providers (id INTEGER PRIMARY KEY AUTOINCREMENT,tenant_id TEXT,provider_type TEXT,name TEXT,base_url TEXT,model TEXT,api_key_encrypted TEXT,input_cost_per_million NUMERIC,output_cost_per_million NUMERIC,active BOOLEAN DEFAULT 1,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''
class ProviderConnectionTests(unittest.TestCase):
 def setUp(self):
  self.engine=create_engine('sqlite://');self.session=Session(self.engine);self.session.execute(text(DDL));self.session.commit();self.key=base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
 def tearDown(self):self.session.close();self.engine.dispose()
 def test_secret_is_encrypted_and_not_returned(self):
  with patch.dict(os.environ,{'API_KEY_ENC_MASTER_KEY':self.key}):
   saved=save_connection(self.session,'ws_1',{'provider_type':'openai','api_key':'sk-super-secret','input_cost_per_million':1,'output_cost_per_million':2})
   raw=self.session.execute(text('SELECT api_key_encrypted FROM workspace_providers')).scalar_one()
   self.assertNotIn('sk-super-secret',raw);self.assertNotIn('api_key',saved)
   runtime=runtime_providers(self.session,'ws_1',[]);self.assertEqual(runtime[0]['apiKey'],'sk-super-secret')
 def test_missing_table_falls_back(self):
  other=create_engine('sqlite://')
  with Session(other) as session:self.assertEqual(runtime_providers(session,'ws', [{'id':'default'}]),[{'id':'default'}])
  other.dispose()
 def test_lists_only_workspace_connections(self):
  with patch.dict(os.environ,{'API_KEY_ENC_MASTER_KEY':self.key}):
   save_connection(self.session,'ws_1',{'provider_type':'openai','api_key':'key1'});save_connection(self.session,'ws_2',{'provider_type':'groq','api_key':'key2'})
  self.assertEqual(len(list_connections(self.session,'ws_1')),1)
 def test_complexity_routes_are_cheap_first(self):
  providers=[{"id":"premium","inputCostPerMillion":10,"outputCostPerMillion":20},{"id":"cheap","inputCostPerMillion":0.2,"outputCostPerMillion":0.4},{"id":"mid","inputCostPerMillion":3,"outputCostPerMillion":15}]
  routes=_complexity_routes(providers)
  self.assertEqual([r["provider"] for r in routes],["cheap","mid","premium"])
  self.assertEqual(routes[-1]["maxComplexity"],10)
  self.assertLess(routes[0]["maxComplexity"],routes[1]["maxComplexity"])
 def test_complexity_routes_empty(self):
  self.assertEqual(_complexity_routes([]),[])
 def test_runtime_settings_uses_cheap_first_routes(self):
  from types import SimpleNamespace
  with patch.dict(os.environ,{'API_KEY_ENC_MASTER_KEY':self.key}):
   save_connection(self.session,'ws_1',{'provider_type':'openai','api_key':'key1','input_cost_per_million':1,'output_cost_per_million':2})
   save_connection(self.session,'ws_1',{'provider_type':'groq','api_key':'key2','input_cost_per_million':0.1,'output_cost_per_million':0.2})
   settings=SimpleNamespace(providers=[],routes=[],max_retries=1,timeout_seconds=30,similarity_threshold=.92,cache_ttl_seconds=86400,port=8787,api_key='x',data_file='')
   rt=runtime_settings(self.session,'ws_1',settings)
  self.assertEqual(len(rt.routes),2)
  self.assertEqual(sorted(r["provider"] for r in rt.routes),['connection-1','connection-2'])
  self.assertEqual(rt.routes[0]["provider"],'connection-2')  # cheaper provider owns the low-complexity tier
if __name__=='__main__':unittest.main()
