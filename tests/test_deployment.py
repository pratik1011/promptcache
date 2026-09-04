"""Deployment configuration tests."""
import unittest

from promptcache.production.db import sync_database_url


class DatabaseUrlTests(unittest.TestCase):
    def test_render_postgres_url_uses_psycopg_driver(self):
        self.assertEqual(
            sync_database_url("postgresql://user:pass@host/db"),
            "postgresql+psycopg://user:pass@host/db",
        )

    def test_asyncpg_url_uses_psycopg_driver(self):
        self.assertEqual(
            sync_database_url("postgresql+asyncpg://user:pass@host/db"),
            "postgresql+psycopg://user:pass@host/db",
        )

    def test_legacy_postgres_scheme_is_supported(self):
        self.assertEqual(
            sync_database_url("postgres://user:pass@host/db"),
            "postgresql+psycopg://user:pass@host/db",
        )

    def test_non_postgres_url_is_unchanged(self):
        self.assertEqual(sync_database_url("sqlite://"), "sqlite://")


if __name__ == "__main__":
    unittest.main()
