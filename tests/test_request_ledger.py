import unittest
from datetime import datetime, UTC
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from promptcache.production.db import UsageEvent
from promptcache.production.repositories import UsageRepository

class RequestLedgerTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite://')
        UsageEvent.__table__.create(self.engine)
        self.session=Session(self.engine)
        for index in range(3):
            self.session.add(UsageEvent(tenant_id='ws_one',provider='mock',cached=index%2==0,
                actual_cost=.01,baseline_cost=.03,saved=.02,latency_ms=20+index,created_at=datetime.now(UTC)))
        self.session.add(UsageEvent(tenant_id='ws_other',provider='mock',cached=False,
            actual_cost=.01,baseline_cost=.01,saved=0,latency_ms=50,created_at=datetime.now(UTC)))
        self.session.commit()
    def tearDown(self):
        self.session.close();self.engine.dispose()
    def test_recent_is_tenant_isolated_and_newest_first(self):
        result=UsageRepository(self.session).recent('ws_one',2)
        self.assertEqual(len(result['items']),2)
        self.assertGreater(result['items'][0]['id'],result['items'][1]['id'])
        self.assertIsNotNone(result['next_cursor'])
    def test_cursor_returns_older_rows(self):
        first=UsageRepository(self.session).recent('ws_one',2)
        second=UsageRepository(self.session).recent('ws_one',2,first['next_cursor'])
        self.assertEqual(len(second['items']),1)
        self.assertLess(second['items'][0]['id'],first['items'][-1]['id'])

if __name__=='__main__': unittest.main()
