"""Structured JSON logging and request-ID propagation.

LOG_FORMAT=json switches promptcache log records to one-JSON-object-per-line;
RequestIdMiddleware stamps every response with X-Request-ID (honoring an
inbound value) and logs method/path/status/duration with the same ID.
"""
import json
import logging
import os
import re
import time
import uuid

REQUEST_ID_HEADER = b"x-request-id"
_SAFE_REQUEST_ID = re.compile(r"[^A-Za-z0-9._-]")


class JsonFormatter(logging.Formatter):
    """One JSON object per log line, including any structured extras."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("request_id", "method", "path", "status", "duration_ms", "tenant"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """Attach the JSON handler to the promptcache logger when LOG_FORMAT=json."""
    if os.getenv("LOG_FORMAT", "").strip().lower() != "json":
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("promptcache")
    logger.handlers = [handler]
    logger.propagate = False


def _inbound_request_id(scope) -> str | None:
    for name, value in scope.get("headers") or []:
        if name.lower() == REQUEST_ID_HEADER:
            candidate = value.decode("latin-1").strip()[:64]
            return _SAFE_REQUEST_ID.sub("", candidate) or None
    return None


class RequestIdMiddleware:
    """Pure ASGI middleware: X-Request-ID on every response + structured access log."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = _inbound_request_id(scope) or uuid.uuid4().hex[:16]
        start = time.monotonic()
        status_holder = {"status": 0}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message.get("status", 0)
                headers = message.setdefault("headers", [])
                headers.append((REQUEST_ID_HEADER, request_id.encode("latin-1")))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.monotonic() - start) * 1000)
            logging.getLogger("promptcache").info(
                "request %s %s -> %s in %sms", scope.get("method"), scope.get("path"),
                status_holder["status"], duration_ms,
                extra={"request_id": request_id, "method": scope.get("method"),
                       "path": scope.get("path"), "status": status_holder["status"],
                       "duration_ms": duration_ms})
