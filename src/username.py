from __future__ import annotations

import re

# Telegram / Discord-ish handles. Require leading @ and 4+ chars total.
_USERNAME_RE = re.compile(
    r"(?<![A-Za-z0-9_])@([A-Za-z][A-Za-z0-9_]{3,31})\b"
)

# Ignore our own bot prompts mistaken for usernames
_BLOCKLIST = {
    "username",
    "user",
    "admin",
    "support",
    "playerok",
    "funpay",
    "here",
    "everyone",
    "nickname",
    "nick",
    "name",
}


def extract_username(text: str | None) -> str | None:
    """Return first plausible @username from chat text, or None."""
    if not text:
        return None
    for match in _USERNAME_RE.finditer(text):
        handle = match.group(1)
        if handle.lower() in _BLOCKLIST:
            continue
        return f"@{handle}"
    return None


def extract_username_from_messages(texts: list[str]) -> str | None:
    """Prefer the latest message that contains a username (scan newest first)."""
    for text in reversed(texts):
        found = extract_username(text)
        if found:
            return found
    return None


def normalize_username(value: str) -> str:
    value = value.strip()
    if not value.startswith("@"):
        value = "@" + value
    return value
