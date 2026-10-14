"""Shared URL validation for web-search results.

Kept provider-neutral so every search backend (Serper, SearXNG) applies the
same boundary: only absolute HTTP(S) URLs with no embedded credentials and no
whitespace/control characters become results. This is the *syntactic* boundary;
it does not resolve DNS or follow redirects (that belongs to any future
page-fetch path, which must additionally block private/loopback destinations
at connection time).
"""

from __future__ import annotations

from urllib.parse import unquote, urlsplit

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_CAMPAIGN_PARAMETERS = frozenset({
    "utm_id", "utm_source", "utm_medium", "utm_campaign", "utm_term",
    "utm_content", "utm_source_platform", "utm_creative_format", "utm_marketing_tactic",
})


def result_identity(url: str) -> str:
    """Compare validated result URLs without campaign attribution parameters."""
    parsed = urlsplit(url)
    # Keep raw query values/order and fragments: either can identify different content.
    query = "&".join(
        part for part in parsed.query.split("&")
        if unquote(part.partition("=")[0]) not in _CAMPAIGN_PARAMETERS
    )
    return parsed._replace(query=query).geturl()


def is_safe_url(value: object) -> bool:
    """True only for absolute HTTP(S) URLs with no userinfo or whitespace.

    Rejects non-strings, blank/untrimmed values, any whitespace or control
    character, non-HTTP(S) schemes, missing hostnames, embedded credentials,
    and malformed ports.
    """
    if not isinstance(value, str):
        return False
    if not value or not value.strip():
        return False
    if value != value.strip():
        return False
    if any(ch.isspace() for ch in value):
        return False
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        return False
    try:
        parsed = urlsplit(value)
        scheme = parsed.scheme.lower()
        if scheme not in _ALLOWED_SCHEMES:
            return False
        if not parsed.hostname:
            return False
        if parsed.username is not None or parsed.password is not None:
            return False
        # Accessing .port raises ValueError on malformed ports; access it to
        # fail closed without leaking the URL.
        _ = parsed.port
    except ValueError:
        return False
    return True


def extract_domain(parsed_or_url: object) -> str:
    """Hostname only — never scheme, port, or credentials."""
    try:
        if isinstance(parsed_or_url, str):
            parsed_or_url = urlsplit(parsed_or_url)
        hostname = parsed_or_url.hostname  # type: ignore[union-attr]
    except (ValueError, AttributeError):
        return ""
    return hostname or ""
