"""Public-social platform classification. No network."""

from __future__ import annotations

import pytest

from trendora.connectors.web_search.platforms import classify_platform


@pytest.mark.parametrize("url,expected", [
    ("https://www.reddit.com/r/x", "Reddit"),
    ("https://reddit.com/r/x", "Reddit"),
    ("https://old.reddit.com/r/x", "Reddit"),
    ("https://www.tiktok.com/@a/video/1", "TikTok"),
    ("https://www.instagram.com/p/abc", "Instagram"),
    ("https://x.com/u/status/1", "X"),
    ("https://twitter.com/u/status/1", "X"),
    ("https://www.linkedin.com/posts/x", "LinkedIn"),
    ("https://www.facebook.com/page/posts/1", "Facebook"),
    ("https://m.facebook.com/page", "Facebook"),
])
def test_known_platforms_and_aliases(url, expected):
    assert classify_platform(url) == expected


@pytest.mark.parametrize("url", [
    "https://reddit.com.evil.example/r/x",   # suffix-spoofed host
    "https://evilreddit.com/r/x",            # not a boundary match
    "https://notreddit.com/",                # no leading dot boundary
    "https://reddit.com.evil.example",       # exact spoof
    "https://x.com.evil.example/1",
    "https://example.com/redirect?to=reddit.com",
])
def test_spoofed_hostnames_are_not_platforms(url):
    assert classify_platform(url) is None


@pytest.mark.parametrize("url", [
    "https://redd.it/abc",       # short link, never followed
    "https://t.co/abc",          # short link
    "https://lnkd.in/abc",       # short link
    "https://fb.me/abc",         # short link
    "https://youtu.be/abc",      # unrelated platform anyway
])
def test_short_links_are_never_guessed(url):
    assert classify_platform(url) is None


@pytest.mark.parametrize("value", ["", "not a url", "javascript:alert(1)", "//reddit.com/r/x"])
def test_non_absolute_urls_are_none(value):
    assert classify_platform(value) is None
