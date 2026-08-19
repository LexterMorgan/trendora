"""Representative YouTube Data API v3 payloads. Not live responses."""

from __future__ import annotations

CHANNEL_A = "UCAAAAAAAAAAAAAAAAAAAAAA"
CHANNEL_B = "UCBBBBBBBBBBBBBBBBBBBBBB"
UPLOADS_A = "UUAAAAAAAAAAAAAAAAAAAAAA"
VIDEO_1 = "videoAAAAAA"
VIDEO_2 = "videoBBBBBB"
VIDEO_3 = "videoCCCCCC"

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
