FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8787
# Apply database migrations (stamp-first for pre-Alembic databases), then serve.
CMD ["sh", "-c", "python -m promptcache.production.migrate && exec uvicorn promptcache.production.app:app --host 0.0.0.0 --port 8787"]
