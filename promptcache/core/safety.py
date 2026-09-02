"""Shared request-safety helpers used by the demo and production gateways."""
import re

# Prompts that embed credentials must never be written to (or served from) the cache.
_SECRET_PATTERN = re.compile(
    r"(sk-[A-Za-z0-9]{16,}|password\s*[:=]|api[_ -]?key\s*[:=]|Bearer\s+[A-Za-z0-9._-]{16,}|card\s*number\s*[:=])",
    re.I,
)


def contains_secret(text: str) -> bool:
    """True when the payload looks like it embeds credentials and must bypass the cache."""
    return bool(_SECRET_PATTERN.search(str(text)))
