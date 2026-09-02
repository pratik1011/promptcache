"""Shared request-safety helpers used by the demo and production gateways."""
import os
import re


# Prompts that embed credentials must never be written to (or served from) the cache.
_SECRET_PATTERN = re.compile(
    r"(sk-[A-Za-z0-9]{16,}|password\s*[:=]|api[_ -]?key\s*[:=]|Bearer\s+[A-Za-z0-9._-]{16,}|card\s*number\s*[:=])",
    re.I,
)

# Heuristic PII detectors applied before prompts are persisted to the cache.
# Redaction errs on the side of privacy; set PII_REDACTION=0 to disable.

def contains_secret(text: str) -> bool:
    """True when the payload looks like it embeds credentials and must bypass the cache."""
    return bool(_SECRET_PATTERN.search(str(text)))


# PII redaction for cached prompts: emails, phone numbers, and card/account-like
# digit runs. Enabled by default (PII_REDACTION=0 opts out); cached entries then
# store a masked copy of the prompt while the provider still sees the original.
# Cache keys are computed from the original prompt, so hits are unaffected.
_PII_PATTERNS = (
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("PHONE", re.compile(r"(?<!\w)(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}(?!\w)")),
    ("SSN", re.compile(r"(?<![\d-])\d{3}-\d{2}-\d{4}(?!\d)")),
    ("CARD", re.compile(r"(?<!\w)\d{13,19}(?!\w)")),
)

def pii_redaction_enabled() -> bool:
    """PII redaction is on by default; PII_REDACTION=0 opts out."""
    return os.getenv("PII_REDACTION", "1").strip().lower() not in {"0", "false", "no", "off"}

def redact_pii(text: str) -> str:
    """Mask emails, phone numbers, government IDs, card numbers, and credential-like strings.

    Only affects what is persisted (cache prompt column, embedding input); cache
    matching keys are computed from the original prompt, so hits are unaffected.
    """
    value = str(text)
    for label, pattern in _PII_PATTERNS:
        value = pattern.sub(f"[REDACTED-{label}]", value)
    return _SECRET_PATTERN.sub("[REDACTED-SECRET]", value)
