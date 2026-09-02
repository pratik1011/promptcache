"""Audit trail writes/reads and failure tolerance."""
import json
import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from promptcache.production.audit import list_audit, record_audit

DDL = """
CREATE TABLE audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id TEXT,
  user_id INTEGER,
  action TEXT NOT NULL,
  target TEXT NOT NULL DEFAULT '',
  detail TEXT NOT NULL DEFAULT '{}',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        with self.engine.begin() as conn:
            conn.execute(text(DDL))
        self.session = Session(self.engine)
        self.addCleanup(self.session.close)

    def test_record_and_list_roundtrip(self):
        record_audit(self.session, "api_key.reveal", tenant_id="t1", user_id=7,
                     target="workspace", detail={"count": 2})
        record_audit(self.session, "workspace.create", tenant_id="t2", user_id=8)
        events = list_audit(self.session, "t1")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["action"], "api_key.reveal")
        self.assertEqual(events[0]["user_id"], 7)
        self.assertEqual(events[0]["detail"], {"count": 2})
        self.assertIn("created_at", events[0])

    def test_detail_is_stored_as_json(self):
        record_audit(self.session, "billing.checkout", user_id=1, detail={"plan": "growth"})
        raw = self.session.execute(text("SELECT detail FROM audit_log")).scalar()
        self.assertEqual(json.loads(raw), {"plan": "growth"})

    def test_failure_never_breaks_caller(self):
        self.session.execute(text("DROP TABLE audit_log"))
        self.session.commit()
        record_audit(self.session, "api_key.create", tenant_id="t1")  # must not raise
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
