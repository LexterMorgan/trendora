"""Representative YouTube Data API v3 payloads. Not live responses."""

from __future__ import annotations

CHANNEL_A = "UCAAAAAAAAAAAAAAAAAAAAAA"
CHANNEL_B = "UCBBBBBBBBBBBBBBBBBBBBBB"
CHANNEL_C = "UCCCCCCCCCCCCCCCCCCCCCCC"
UPLOADS_A = "UUAAAAAAAAAAAAAAAAAAAAAA"
VIDEO_1 = "videoAAAAAA"
VIDEO_2 = "videoBBBBBB"
VIDEO_3 = "videoCCCCCC"
VIDEO_CHART_1 = "videoCHART01"
VIDEO_NO_CHANNEL = "videoNOCHAN1"

CHANNELS_LIST_OK = {
    "kind": "youtube#channelListResponse",
    "items": [
        {
            "kind": "youtube#channel",
            "id": CHANNEL_A,
            "snippet": {
                "title": "SEA AI Education",
                "description": "Lessons about AI",
                "customUrl": "@seaai",
                "publishedAt": "2018-02-01T10:00:00Z",
                "country": "ID",
            },
            "contentDetails": {"relatedPlaylists": {"uploads": UPLOADS_A}},
            "statistics": {
                "viewCount": "1000",
                "subscriberCount": "50",
                "hiddenSubscriberCount": False,
                "videoCount": "3",
            },
        }
    ],
}

CHANNELS_LIST_MISSING_UPLOADS = {
    "items": [
        {
            "id": CHANNEL_A,
            "snippet": {"title": "No uploads playlist"},
            "contentDetails": {"relatedPlaylists": {}},
            "statistics": {"viewCount": "1"},
        }
    ]
}

CHANNELS_LIST_HIDDEN_SUBSCRIBERS = {
    "items": [
        {
            "id": CHANNEL_A,
            "snippet": {"title": "Hidden subs", "country": "US"},
            "contentDetails": {"relatedPlaylists": {"uploads": UPLOADS_A}},
            "statistics": {
                "viewCount": "9",
                "hiddenSubscriberCount": True,
                "subscriberCount": "50",
                "videoCount": "1",
            },
        }
    ]
}

PLAYLIST_PAGE_1 = {
    "nextPageToken": "PAGE2",
    "items": [
        {"contentDetails": {"videoId": VIDEO_1, "videoPublishedAt": "2024-01-01T00:00:00Z"}},
        {"contentDetails": {"videoId": VIDEO_2, "videoPublishedAt": "2024-01-02T00:00:00Z"}},
    ],
}

PLAYLIST_PAGE_2 = {
    "items": [
        {"contentDetails": {"videoId": VIDEO_3}},
    ]
}

PLAYLIST_MISSING_VIDEO_ID = {
    "items": [
        {"contentDetails": {}},
        {"contentDetails": {"videoId": VIDEO_1}},
    ]
}

VIDEOS_LIST_OK = {
    "items": [
        {
            "id": VIDEO_1,
            "snippet": {
                "title": "Intro to Python",
                "description": "A lesson",
                "channelId": CHANNEL_A,
                "publishedAt": "2024-01-01T12:00:00Z",
                "categoryId": "27",
                "tags": ["python", "education"],
            },
            "contentDetails": {"duration": "PT10M3S", "definition": "hd", "caption": "false"},
            "statistics": {
                "viewCount": "100",
                "likeCount": "10",
                "commentCount": "2",
                "favoriteCount": "0",
            },
        },
        {
            "id": VIDEO_2,
            "snippet": {
                "title": "Stats missing likes",
                "channelId": CHANNEL_A,
                "publishedAt": "2024-01-02T12:00:00Z",
            },
            "statistics": {"viewCount": "5"},
        },
    ]
}

VIDEOS_LIST_MALFORMED_STATS = {
    "items": [
        {
            "id": VIDEO_1,
            "snippet": {"title": "Bad stats", "channelId": CHANNEL_A},
            "statistics": {"viewCount": "not-a-number", "likeCount": "-3", "commentCount": "4"},
        }
    ]
}

VIDEOS_LIST_NO_STATS = {
    "items": [
        {
            "id": VIDEO_1,
            "snippet": {"title": "No stats", "channelId": CHANNEL_A, "publishedAt": "not-a-date"},
        }
    ]
}

QUOTA_ERROR = {
    "error": {
        "code": 403,
        "message": "The request cannot be completed because you have exceeded your quota.",
        "errors": [{"domain": "youtube.quota", "reason": "quotaExceeded"}],
    }
}

MALFORMED_LIST_ITEMS = {"items": "not-a-list"}

VIDEO_CATEGORIES_ID = {
    "kind": "youtube#videoCategoryListResponse",
    "items": [
        {
            "kind": "youtube#videoCategory",
            "id": "24",
            "snippet": {"title": "Entertainment", "assignable": True},
        },
        {
            "kind": "youtube#videoCategory",
            "id": "27",
            "snippet": {"title": "Education", "assignable": True},
        },
        {
            "kind": "youtube#videoCategory",
            "id": "28",
            "snippet": {"title": "Science & Technology", "assignable": True},
        },
    ],
}

VIDEO_CATEGORIES_SG = {
    "kind": "youtube#videoCategoryListResponse",
    "items": [
        {
            "kind": "youtube#videoCategory",
            "id": "24",
            "snippet": {"title": "Entertainment", "assignable": True},
        },
        {
            "kind": "youtube#videoCategory",
            "id": "27",
            "snippet": {"title": "Education (SG)", "assignable": True},
        },
        {
            "kind": "youtube#videoCategory",
            "id": "28",
            "snippet": {"title": "Science & Technology", "assignable": True},
        },
    ],
}


def _chart_video(
    video_id: str,
    *,
    channel_id: str | None,
    title: str,
    category_id: str = "27",
    view_count: str = "100",
) -> dict:
    snippet: dict = {
        "title": title,
        "publishedAt": "2024-06-01T00:00:00Z",
        "categoryId": category_id,
    }
    if channel_id is not None:
        snippet["channelId"] = channel_id
    return {
        "id": video_id,
        "snippet": snippet,
        "contentDetails": {"duration": "PT1M", "definition": "hd", "caption": "false"},
        "statistics": {
            "viewCount": view_count,
            "likeCount": "1",
            "commentCount": "0",
        },
    }


MOSTPOPULAR_ID_PAGE_1 = {
    "nextPageToken": "PAGE2",
    "items": [
        _chart_video(VIDEO_1, channel_id=CHANNEL_A, title="Intro to Python", category_id="27"),
        _chart_video(VIDEO_2, channel_id=CHANNEL_A, title="Stats missing likes", category_id="27"),
    ],
}

MOSTPOPULAR_ID_PAGE_2 = {
    "items": [
        _chart_video(
            VIDEO_CHART_1,
            channel_id=CHANNEL_C,
            title="US viral clip",
            category_id="24",
            view_count="9000",
        ),
    ]
}

MOSTPOPULAR_SG = {
    "items": [
        _chart_video(VIDEO_1, channel_id=CHANNEL_A, title="Intro to Python", category_id="27"),
        _chart_video(
            VIDEO_CHART_1,
            channel_id=CHANNEL_C,
            title="US viral clip",
            category_id="24",
            view_count="9000",
        ),
    ]
}

MOSTPOPULAR_EMPTY = {"items": []}

MOSTPOPULAR_NO_CHANNEL_ID = {
    "items": [
        _chart_video(VIDEO_NO_CHANNEL, channel_id=None, title="Orphan chart video"),
        _chart_video(VIDEO_1, channel_id=CHANNEL_A, title="Intro to Python"),
    ]
}

CHANNELS_LIST_A_AND_C = {
    "kind": "youtube#channelListResponse",
    "items": [
        CHANNELS_LIST_OK["items"][0],
        {
            "kind": "youtube#channel",
            "id": CHANNEL_C,
            "snippet": {
                "title": "US Chart Channel",
                "description": "Not a SEA publisher",
                "customUrl": "@uschart",
                "publishedAt": "2019-01-01T00:00:00Z",
                "country": "US",
            },
            "contentDetails": {"relatedPlaylists": {"uploads": "UUCCCCCCCCCCCCCCCCCCCCCC"}},
            "statistics": {
                "viewCount": "50000",
                "subscriberCount": "800",
                "hiddenSubscriberCount": False,
                "videoCount": "12",
            },
        },
    ],
}

SEARCH_PAGE_1 = {
    "kind": "youtube#searchListResponse",
    "nextPageToken": "SEARCHPAGE2",
    "items": [
        {
            "kind": "youtube#searchResult",
            "id": {"kind": "youtube#video", "videoId": VIDEO_1},
            "snippet": {
                "title": "Intro to Python",
                "description": "Learn Python basics in this lesson.",
                "publishedAt": "2024-01-01T12:00:00Z",
                "channelId": CHANNEL_A,
                "channelTitle": "SEA AI Education",
            },
        },
        {
            "kind": "youtube#searchResult",
            "id": {"kind": "youtube#video", "videoId": VIDEO_2},
            "snippet": {
                "title": "Stats missing likes",
                "description": "Second search result.",
                "publishedAt": "2024-01-02T12:00:00Z",
                "channelId": CHANNEL_A,
                "channelTitle": "SEA AI Education",
            },
        },
    ],
}

SEARCH_PAGE_2 = {
    "kind": "youtube#searchListResponse",
    "items": [
        {
            "kind": "youtube#searchResult",
            "id": {"kind": "youtube#video", "videoId": VIDEO_3},
            "snippet": {
                "title": "Advanced Python",
                "description": "Deeper Python topics.",
                "publishedAt": "2024-01-03T12:00:00Z",
                "channelId": CHANNEL_B,
                "channelTitle": "Tech Channel B",
            },
        },
    ],
}

SEARCH_SINGLE_PAGE_NO_TOKEN = {
    "kind": "youtube#searchListResponse",
    "items": [
        {
            "kind": "youtube#searchResult",
            "id": {"kind": "youtube#video", "videoId": VIDEO_1},
            "snippet": {
                "title": "Only result",
                "description": "A single result.",
                "publishedAt": "2024-01-01T00:00:00Z",
                "channelTitle": "SEA AI Education",
            },
        },
    ],
}

SEARCH_MIXED_KINDS = {
    "kind": "youtube#searchListResponse",
    "items": [
        {
            "kind": "youtube#searchResult",
            "id": {"kind": "youtube#channel", "channelId": CHANNEL_C},
            "snippet": {"title": "A channel result", "publishedAt": "2024-01-01T00:00:00Z"},
        },
        {
            "kind": "youtube#searchResult",
            "id": {"kind": "youtube#video", "videoId": VIDEO_1},
            "snippet": {"title": "A video result", "publishedAt": "2024-01-02T00:00:00Z"},
        },
    ],
}

SEARCH_EMPTY = {"kind": "youtube#searchListResponse", "items": []}
