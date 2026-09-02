# Production deployment

This package is the deployment boundary for the FastAPI/Postgres/pgvector/Redis version.
The current standard-library server remains available through `python run.py` while infrastructure is configured.

Required services:
- PostgreSQL with the `vector` extension
- Redis

The production implementation should move persistence and semantic lookup behind the interfaces in `promptcache/cache/ports` and `promptcache/db`.
