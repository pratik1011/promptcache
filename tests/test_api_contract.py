'''Regression coverage for dashboard-to-API route contracts.'''
import unittest
from pathlib import Path


class DashboardRouteContractTests(unittest.TestCase):
    def test_dashboard_backed_routes_are_registered(self):
        source = Path('promptcache/production/app.py').read_text(encoding='utf-8')
        required_paths = {
            '/v1/auth/change-password',
            '/v1/account/export',
            '/v1/workspaces/{tenant_id}/activation',
            '/v1/workspaces/{tenant_id}/alerts',
            '/v1/workspaces/{tenant_id}/notifications',
            '/v1/workspaces/{tenant_id}/audit',
            '/v1/workspaces/{tenant_id}/reliability',
            '/v1/workspaces/{tenant_id}/baseline',
        }
        missing = {path for path in required_paths if path not in source}
        self.assertFalse(missing, missing)
