"""YouTube HTTP client tests. All responses are mocked; no network."""

import httpx
import pytest

from trendora.connectors.youtube.client import YouTubeClient
from trendora.connectors.youtube.exceptions import (
    YouTubeApiError,
    YouTubeConfigurationError,
    YouTubeHttpError,
    YouTubeResponseError,
)
from tests.fixtures.youtube_responses import (
    CHANNEL_A,
    CHANNELS_LIST_OK,
    MALFORMED_LIST_ITEMS,
    PLAYLIST_MISSING_VIDEO_ID,
    PLAYLIST_PAGE_1,
    PLAYLIST_PAGE_2,
    QUOTA_ERROR,
    UPLOADS_A,
    VIDEO_1,
    VIDEO_2,
    VIDEO_3,
    VIDEOS_LIST_OK,
)

TEST_KEY = "test-key-not-real"


def _client(handler) -> YouTubeClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    return YouTubeClient(TEST_KEY, http_client=http)


def test_client_requires_api_key() -> None:
    with pytest.raises(YouTubeConfigurationError, match="YOUTUBE_API_KEY"):
        YouTubeClient("  ")


def test_client_constructs_without_request() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"items": []})

    client = _client(handler)
    assert calls == []
    client.close()


def test_channels_list_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/channels")
        assert request.url.params["key"] == TEST_KEY
        assert "search" not in request.url.path
        return httpx.Response(200, json=CHANNELS_LIST_OK)

    channels = _client(handler).list_channels([CHANNEL_A])
    assert len(channels) == 1
    assert channels[0].id == CHANNEL_A
    assert channels[0].uploads_playlist_id == UPLOADS_A
    assert channels[0].snippet.title == "SEA AI Education"


def test_playlist_pagination_stops_at_limit_without_next_page() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path.endswith("/playlistItems")
        if request.url.params.get("pageToken"):
            raise AssertionError("must not request page 2 when limit is already satisfied")
        return httpx.Response(200, json=PLAYLIST_PAGE_1)

    ids = _client(handler).list_upload_video_ids(UPLOADS_A, limit=2)
    assert ids == [VIDEO_1, VIDEO_2]
    assert calls == 1


def test_playlist_pagination_follows_next_page_token() -> None:
    calls: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        token = request.url.params.get("pageToken")
        calls.append(token)
        if token == "PAGE2":
            return httpx.Response(200, json=PLAYLIST_PAGE_2)
        return httpx.Response(200, json=PLAYLIST_PAGE_1)

    ids = _client(handler).list_upload_video_ids(UPLOADS_A, limit=10)
    assert ids == [VIDEO_1, VIDEO_2, VIDEO_3]
    assert calls == [None, "PAGE2"]


def test_playlist_skips_items_without_video_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=PLAYLIST_MISSING_VIDEO_ID)

    ids = _client(handler).list_upload_video_ids(UPLOADS_A, limit=10)
    assert ids == [VIDEO_1]


def test_videos_list_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/videos")
        assert VIDEO_1 in request.url.params["id"]
        return httpx.Response(200, json=VIDEOS_LIST_OK)

    videos = _client(handler).list_videos([VIDEO_1, VIDEO_2])
    assert [video.id for video in videos] == [VIDEO_1, VIDEO_2]
    assert videos[0].statistics["viewCount"] == "100"


def test_quota_error_is_visible() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json=QUOTA_ERROR)

    with pytest.raises(YouTubeApiError, match="quotaExceeded") as exc_info:
        _client(handler).list_channels([CHANNEL_A])
    assert exc_info.value.status_code == 403
    assert exc_info.value.reason == "quotaExceeded"
    assert TEST_KEY not in str(exc_info.value)


def test_http_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns failed", request=request)

    with pytest.raises(YouTubeHttpError, match="HTTP request failed"):
        _client(handler).list_channels([CHANNEL_A])


def test_malformed_items_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=MALFORMED_LIST_ITEMS)

    with pytest.raises(YouTubeResponseError, match="items"):
        _client(handler).list_channels([CHANNEL_A])


def test_non_json_error_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream exploded")

    with pytest.raises(YouTubeApiError, match="500"):
        _client(handler).list_channels([CHANNEL_A])


def test_api_key_is_not_written_to_logs(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=CHANNELS_LIST_OK)

    with caplog.at_level("INFO", logger="trendora.connectors.youtube.client"):
        _client(handler).list_channels([CHANNEL_A])
    combined = "\n".join(record.getMessage() for record in caplog.records)
    assert TEST_KEY not in combined
    assert "key=" not in combined
