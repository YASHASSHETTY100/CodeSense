"""Security, secret redaction, and file categorization utilities."""
from __future__ import annotations
import os, re

# Configurable regexes for secret detection
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (?:[A-Z0-9_-]+ )?PRIVATE KEY-----[\s\S]*?-----END (?:[A-Z0-9_-]+ )?PRIVATE KEY-----",
    re.MULTILINE,
)

_CONN_STR_RE = re.compile(
    r"""\b(?:postgres|postgresql|mysql|mongodb(?:\+srv)?|redis|amqp|mssql|oracle):\/\/[^\s'":]+:[^\s'@"]+@[^\s'"`]+""",
    re.IGNORECASE,
)

_BASIC_AUTH_URL_RE = re.compile(
    r"""https?:\/\/[^\s'":]+:([^\s'@"]+)@""",
    re.IGNORECASE,
)

_API_KEY_PATTERNS = [
    (re.compile(r"\b(?:sk-[a-zA-Z0-9_-]{20,}|sk-ant-[a-zA-Z0-9_-]{20,})\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{36,}\b"), "[REDACTED_TOKEN]"),
    (re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"), "[REDACTED_TOKEN]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9._-]{10,}\.[A-Za-z0-9._-]{10,}\b"), "[REDACTED_JWT_TOKEN]"),
    (re.compile(r"(?i)\b(?:aws_secret_access_key|secret_key|secret)\s*[:= ]\s*([A-Za-z0-9/+=]{40})\b"), "[REDACTED_SECRET_KEY]"),
]

_GENERIC_SECRET_RE = re.compile(
    r"""(?i)(['"]?(?:password|passwd|pwd|secret|client_secret|api_key|apikey|access_token|auth_token|bearer_token)['"]?\s*[:=]\s*)(['"](?!\[REDACTED_)[^'"\r\n]{4,}['"])"""
)


def redact_secrets(text: str) -> str:
    """Scrub all passwords, tokens, API keys, client secrets, private keys, and connection strings."""
    if not text:
        return text

    # 1. Private keys
    text = _PRIVATE_KEY_RE.sub("[REDACTED_PRIVATE_KEY]", text)

    # 2. Connection strings
    text = _CONN_STR_RE.sub("[REDACTED_CONNECTION_STRING]", text)

    # 3. Basic auth in URLs
    text = _BASIC_AUTH_URL_RE.sub(lambda m: m.group(0).replace(m.group(1), "[REDACTED_CREDENTIAL]"), text)

    # 4. Known key patterns
    for pat, repl in _API_KEY_PATTERNS:
        text = pat.sub(repl, text)

    # 5. Generic key-value secrets
    text = _GENERIC_SECRET_RE.sub(r'\1"[REDACTED_SECRET]"', text)

    return text


def contains_secrets(text: str) -> bool:
    """Check if any secret pattern is present."""
    if not text:
        return False
    if _PRIVATE_KEY_RE.search(text) or _CONN_STR_RE.search(text) or _BASIC_AUTH_URL_RE.search(text):
        return True
    for pat, _ in _API_KEY_PATTERNS:
        if pat.search(text):
            return True
    if _GENERIC_SECRET_RE.search(text):
        return True
    return False


# File classification utilities
_TEST_PATH_RE = re.compile(
    r"(?:^|[/\\])(?:tests?|__tests__|specs?)(?:[/\\])|(?:^|[._-])(?:test|spec)[._-]|(?:test_|spec_)",
    re.IGNORECASE,
)

_UTIL_PATH_RE = re.compile(
    r"(?:^|[/\\])(?:utils?|helpers?|common|config|conftest|setup)(?:\.[a-zA-Z0-9]+$|[/\\])",
    re.IGNORECASE,
)


def is_test_file(path: str) -> bool:
    """Return True if path represents a test file or test directory."""
    normalized = path.replace("\\", "/")
    return bool(_TEST_PATH_RE.search(normalized))


def is_util_file(path: str) -> bool:
    """Return True if path represents generic utility/configuration files."""
    normalized = path.replace("\\", "/")
    return bool(_UTIL_PATH_RE.search(normalized))


_VENDOR_ASSET_PATH_RE = re.compile(
    r"(?:^|[/\\])(?:static_in_env|node_modules|vendor|bower_components|dist|build)[/\\].*|\.min\.(?:js|css)$",
    re.IGNORECASE,
)


def is_vendor_asset_file(path: str) -> bool:
    """Return True if path represents third-party vendor assets (minified JS/CSS, node_modules, static_in_env)."""
    normalized = path.replace("\\", "/")
    return bool(_VENDOR_ASSET_PATH_RE.search(normalized))


def is_binary_content(sample_bytes: bytes) -> bool:
    """Check if sample bytes contain null bytes indicating compiled binary data."""
    if not sample_bytes:
        return False
    return b"\x00" in sample_bytes[:1024]
