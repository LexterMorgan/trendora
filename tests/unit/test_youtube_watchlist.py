"""Watchlist parsing tests."""

import pytest

from trendora.connectors.youtube.exceptions import InvalidYouTubeWatchlistError
from trendora.connectors.youtube.watchlist import parse_channel_ids
from tests.fixtures.youtube_responses import CHANNEL_A, CHANNEL_B


def test_empty_watchlist_is_empty_tuple() -> None:
    assert parse_channel_ids(None) == ()
    assert parse_channel_ids("") == ()
    assert parse_channel_ids("  ,  , ") == ()


def test_parse_trims_and_deduplicates_preserving_order() -> None:
    raw = f" {CHANNEL_A}, {CHANNEL_B}, {CHANNEL_A}, {CHANNEL_B} "
    assert parse_channel_ids(raw) == (CHANNEL_A, CHANNEL_B)


def test_trailing_commas_are_ignored() -> None:
    assert parse_channel_ids(f"{CHANNEL_A},") == (CHANNEL_A,)


def test_rejects_handles_and_urls() -> None:
    with pytest.raises(InvalidYouTubeWatchlistError, match="UC"):
        parse_channel_ids("@seaai")
    with pytest.raises(InvalidYouTubeWatchlistError):
        parse_channel_ids("https://www.youtube.com/channel/" + CHANNEL_A)


def test_rejects_short_or_garbage_ids() -> None:
    with pytest.raises(InvalidYouTubeWatchlistError):
        parse_channel_ids("UCSHORT")
    with pytest.raises(InvalidYouTubeWatchlistError):
        parse_channel_ids("not-a-channel")
