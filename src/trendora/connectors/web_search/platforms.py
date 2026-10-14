"""Platform classification for public-social discovery (SearXNG only).

Search-engine query syntax can vary and a ``site:`` operator is a hint, not a
guarantee, so the returned hostname is what decides a platform. Matching uses
exact hostname/domain boundaries: a host matches a domain only when it is that
domain or a subdomain of it, so ``reddit.com.evil.example`` never counts as
Reddit.

Shorteners and redirect hosts (``redd.it``, ``t.co``, ``lnkd.in``, ``fb.me``,
``youtu.be``, ...) are deliberately absent: a short link is never followed or
guessed into a platform. Where a platform genuinely uses more than one
hostname, the alias is listed explicitly (X: ``x.com`` and ``twitter.com``).
"""

from __future__ import annotations

from urllib.parse import urlsplit

# Canonical platform label -> explicit hostname domains. Order is display order.
PLATFORM_DOMAINS: dict[str, tuple[str, ...]] = {
    "Reddit": ("reddit.com",),
    "TikTok": ("tiktok.com",),
    "Instagram": ("instagram.com",),
    "X": ("x.com", "twitter.com"),
    "LinkedIn": ("linkedin.com",),
    "Facebook": ("facebook.com",),
}

# The domain used to build one bounded ``site:`` query per platform.
PLATFORM_QUERY_DOMAINS: tuple[str, ...] = (
    "reddit.com",
    "tiktok.com",
    "instagram.com",
    "x.com",
    "linkedin.com",
    "facebook.com",
)


def _hostname(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in ("http", "https"):
        return ""
    host = parsed.hostname
    return (host or "").lower().rstrip(".")


def classify_platform(url: str) -> str | None:
    """Canonical platform label for an absolute URL, or ``None``.

    Exact hostname/domain boundary matching only; no short links, no redirects.
    """
    host = _hostname(url)
    if not host:
        return None
    for platform, domains in PLATFORM_DOMAINS.items():
        for domain in domains:
            if host == domain or host.endswith("." + domain):
                return platform
    return None
