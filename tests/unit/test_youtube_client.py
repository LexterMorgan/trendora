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
    CHANNEL_C,
    CHANNELS_LIST_OK,
    MALFORMED_LIST_ITEMS,
    MOSTPOPULAR_EMPTY,
    MOSTPOPULAR_ID_PAGE_1,
    MOSTPOPULAR_ID_PAGE_2,
    PLAYLIST_MISSING_VIDEO_ID,
    PLAYLIST_PAGE_1,
    PLAYLIST_PAGE_2,
    QUOTA_ERROR,
    SEARCH_EMPTY,
    SEARCH_MIXED_KINDS,
    SEARCH_PAGE_1,
    SEARCH_PAGE_2,
    SEARCH_SINGLE_PAGE_NO_TOKEN,
    UPLOADS_A,
    VIDEO_1,
    VIDEO_2,
    VIDEO_3,
    VIDEO_CHART_1,
    VIDEO_CATEGORIES_ID,
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


def test_video_categories_request_params() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/videoCategories")
        assert request.url.params["part"] == "snippet"
        assert request.url.params["regionCode"] == "ID"
        assert request.url.params["key"] == TEST_KEY
        assert "id" not in request.url.params
        assert "search" not in request.url.path
        return httpx.Response(200, json=VIDEO_CATEGORIES_ID)

    categories = _client(handler).list_video_categories("ID")
    assert [category.id for category in categories] == ["24", "27", "28"]
    titles = {category.id: category.snippet.title for category in categories}
    assert titles["27"] == "Education"


def test_most_popular_request_params() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/videos")
        assert request.url.params["part"] == "snippet,contentDetails,statistics"
        assert request.url.params["chart"] == "mostPopular"
        assert request.url.params["regionCode"] == "TH"
        assert int(request.url.params["maxResults"]) <= 50
        assert "id" not in request.url.params
        assert "search" not in request.url.path
        return httpx.Response(200, json=MOSTPOPULAR_ID_PAGE_1)

    videos = _client(handler).list_most_popular_videos("TH", max_videos=2)
    assert [video.id for video in videos] == [VIDEO_1, VIDEO_2]
    assert videos[0].snippet.channel_id == CHANNEL_A


def test_most_popular_pagination_stops_at_max_videos() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.params["chart"] == "mostPopular"
        assert request.url.params["regionCode"] == "ID"
        if request.url.params.get("pageToken"):
            raise AssertionError("must not request page 2 when max_videos is already satisfied")
        assert request.url.params["maxResults"] == "2"
        return httpx.Response(200, json=MOSTPOPULAR_ID_PAGE_1)

    videos = _client(handler).list_most_popular_videos("ID", max_videos=2)
    assert [video.id for video in videos] == [VIDEO_1, VIDEO_2]
    assert calls == 1


def test_most_popular_pagination_follows_next_page_token() -> None:
    calls: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        token = request.url.params.get("pageToken")
        calls.append(token)
        remaining_hint = int(request.url.params["maxResults"])
        assert remaining_hint <= 50
        if token == "PAGE2":
            return httpx.Response(200, json=MOSTPOPULAR_ID_PAGE_2)
        return httpx.Response(200, json=MOSTPOPULAR_ID_PAGE_1)

    videos = _client(handler).list_most_popular_videos("ID", max_videos=10)
    assert [video.id for video in videos] == [VIDEO_1, VIDEO_2, VIDEO_CHART_1]
    assert videos[2].snippet.channel_id == CHANNEL_C
    assert calls == [None, "PAGE2"]


def test_most_popular_max_results_never_exceeds_fifty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert int(request.url.params["maxResults"]) == 50
        return httpx.Response(200, json=MOSTPOPULAR_EMPTY)

    videos = _client(handler).list_most_popular_videos("MY", max_videos=80)
    assert videos == []


def test_most_popular_empty_chart() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=MOSTPOPULAR_EMPTY)

    assert _client(handler).list_most_popular_videos("VN", max_videos=50) == []


def test_most_popular_quota_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json=QUOTA_ERROR)

    with pytest.raises(YouTubeApiError, match="quotaExceeded") as exc_info:
        _client(handler).list_most_popular_videos("PH", max_videos=10)
    assert exc_info.value.reason == "quotaExceeded"


def test_video_categories_malformed_items() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=MALFORMED_LIST_ITEMS)

    with pytest.raises(YouTubeResponseError, match="items"):
        _client(handler).list_video_categories("ID")


def test_most_popular_skips_malformed_video_resources() -> None:
    payload = {
        "items": [
            {"snippet": {"title": "missing id"}},
            MOSTPOPULAR_ID_PAGE_1["items"][0],
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    videos = _client(handler).list_most_popular_videos("ID", max_videos=10)
    assert [video.id for video in videos] == [VIDEO_1]


def test_most_popular_malformed_items_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=MALFORMED_LIST_ITEMS)

    with pytest.raises(YouTubeResponseError, match="items"):
        _client(handler).list_most_popular_videos("ID", max_videos=10)


def test_watchlist_videos_list_still_uses_ids_not_chart() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/videos")
        assert "chart" not in request.url.params
        assert VIDEO_1 in request.url.params["id"]
        return httpx.Response(200, json=VIDEOS_LIST_OK)

    videos = _client(handler).list_videos([VIDEO_1, VIDEO_2])
    assert [video.id for video in videos] == [VIDEO_1, VIDEO_2]


def test_search_single_page_builds_correct_params() -> None:
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(dict(request.url.params))
        assert request.url.path.endswith("/search")
        assert request.url.params["key"] == TEST_KEY
        assert request.url.params["q"] == "AI education"
        assert request.url.params["regionCode"] == "SG"
        assert request.url.params["type"] == "video"
        assert request.url.params["order"] == "relevance"
        assert request.url.params["maxResults"] == "50"
        assert request.url.params["publishedAfter"] == "2026-08-01T00:00:00Z"
        assert request.url.params["publishedBefore"] == "2026-08-31T00:00:00Z"
        return httpx.Response(200, json=SEARCH_PAGE_1)

    results = _client(handler).search_videos(
        query="AI education",
        region_code="SG",
        published_after="2026-08-01T00:00:00Z",
        published_before="2026-08-31T00:00:00Z",
        limit=50,
    )
    assert [r.video_id for r in results] == [VIDEO_1, VIDEO_2]
    assert len(captured) == 1


def test_search_paginates_up_to_two_pages_for_limit_over_fifty() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params.get("pageToken"))
        if request.url.params.get("pageToken") == "SEARCHPAGE2":
            return httpx.Response(200, json=SEARCH_PAGE_2)
        return httpx.Response(200, json=SEARCH_PAGE_1)

    results = _client(handler).search_videos(
        query="python",
        region_code="SG",
        published_after=None,
        published_before=None,
        limit=55,
    )
    assert [r.video_id for r in results] == [VIDEO_1, VIDEO_2, VIDEO_3]
    assert calls == [None, "SEARCHPAGE2"]


def test_search_stops_when_next_page_token_absent() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=SEARCH_SINGLE_PAGE_NO_TOKEN)

    results = _client(handler).search_videos(
        query="python",
        region_code="SG",
        published_after=None,
        published_before=None,
        limit=55,
    )
    assert [r.video_id for r in results] == [VIDEO_1]
    assert len(calls) == 1


def test_search_never_returns_more_than_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SEARCH_PAGE_1)

    results = _client(handler).search_videos(
        query="python",
        region_code="SG",
        published_after=None,
        published_before=None,
        limit=3,
    )
    assert [r.video_id for r in results] == [VIDEO_1, VIDEO_2]
    assert len(results) <= 3


def test_search_dedupes_video_ids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = {
            "items": [
                {"id": {"kind": "youtube#video", "videoId": VIDEO_1}, "snippet": {"title": "A"}},
                {"id": {"kind": "youtube#video", "videoId": VIDEO_1}, "snippet": {"title": "B"}},
                {"id": {"kind": "youtube#video", "videoId": VIDEO_2}, "snippet": {"title": "C"}},
            ]
        }
        return httpx.Response(200, json=payload)

    results = _client(handler).search_videos(
        query="python",
        region_code="SG",
        published_after=None,
        published_before=None,
        limit=10,
    )
    assert [r.video_id for r in results] == [VIDEO_1, VIDEO_2]


def test_search_skips_items_without_video_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SEARCH_MIXED_KINDS)

    results = _client(handler).search_videos(
        query="python",
        region_code="SG",
        published_after=None,
        published_before=None,
        limit=10,
    )
    assert [r.video_id for r in results] == [VIDEO_1]


def test_search_zero_limit_returns_empty_without_calls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    assert _client(handler).search_videos(
        query="python",
        region_code="SG",
        published_after=None,
        published_before=None,
        limit=0,
    ) == []


def test_search_empty_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SEARCH_EMPTY)

    assert _client(handler).search_videos(
        query="python",
        region_code="SG",
        published_after=None,
        published_before=None,
        limit=10,
    ) == []
