"""Container-entrypoint migration bootstrap.

Brings the database to the latest Alembic revision on boot:

- Fresh database (no ``users`` table): ``alembic upgrade head`` creates the
  full schema from the baseline migration.
- Database provisioned before Alembic existed (tables present, no
  ``alembic_version`` row): ``alembic stamp head`` registers the baseline as
  already applied, then any newer revisions apply normally.

Run as ``python -m promptcache.production.migrate``; exits non-zero on failure
so the container does not serve traffic against an unmigrated schema.
"""
import sys

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from .db import SYNC_DATABASE_URL


def main() -> int:
    engine = create_engine(SYNC_DATABASE_URL)
    try:
        tables = set(inspect(engine).get_table_names())
        config = Config("alembic.ini")
        if "users" in tables and "alembic_version" not in tables:
            print("pre-Alembic schema detected; stamping baseline as applied", flush=True)
            command.stamp(config, "head")
        command.upgrade(config, "head")
        print("database migrations up to date", flush=True)
        return 0
    except Exception as exc:
        print(f"migration bootstrap failed: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
