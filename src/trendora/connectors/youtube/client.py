"""YouTube Data API v3 HTTP client. No SQLAlchemy. No normalization."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

import httpx
from pydantic import ValidationError

from trendora.connectors.youtube.exceptions import (
    YouTubeApiError,
    YouTubeConfigurationError,
    YouTubeHttpError,
    YouTubeResponseError,
)
from trendora.connectors.youtube.schemas import ChannelResource, VideoCategoryResource, VideoResource

logger = logging.getLogger("trendora.connectors.youtube.client")

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
_MAX_IDS_PER_REQUEST = 50
_USER_AGENT = "Trendora/0.0.1"


class YouTubeClient:
    """HTTPS client for YouTube Data API v3 list operations.

    Implemented methods: channels.list, playlistItems.list, videos.list
    (by id or chart=mostPopular), and videoCategories.list.
    search.list is intentionally not implemented.
    """

    def __init__(self, api_key: str, *, http_client: httpx.Client | None = None) -> None:
        key = api_key.strip()
        if not key:
            raise YouTubeConfigurationError(
                "YOUTUBE_API_KEY is not set. Copy .env.example to .env and add a "
                "YouTube Data API v3 key from Google Cloud Console."
            )
        self._api_key = key
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(
            timeout=httpx.Timeout(20.0, connect=10.0),
            headers={"User-Agent": _USER_AGENT},
        )

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> YouTubeClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def list_channels(self, channel_ids: Sequence[str]) -> list[ChannelResource]:
        resources: list[ChannelResource] = []
        unique_ids = list(dict.fromkeys(channel_ids))
        for chunk in _chunks(unique_ids, _MAX_IDS_PER_REQUEST):
            payload = self._get(
                "channels",
                {
                    "part": "snippet,contentDetails,statistics",
                    "id": ",".join(chunk),
                    "maxResults": _MAX_IDS_PER_REQUEST,
                },
            )
            for raw in _items(payload):
                try:
                    resources.append(ChannelResource.model_validate(raw))
                except ValidationError:
                    logger.warning("youtube.channel.invalid_resource skipped malformed item")
        logger.info("youtube.channels.listed requested=%s returned=%s", len(unique_ids), len(resources))
        return resources

    def list_upload_video_ids(self, uploads_playlist_id: str, *, limit: int) -> list[str]:
        if limit < 1:
            return []
        video_ids: list[str] = []
        page_token: str | None = None
        page = 0
        while len(video_ids) < limit:
            page += 1
            remaining = limit - len(video_ids)
            params: dict[str, str | int] = {
                "part": "contentDetails",
                "playlistId": uploads_playlist_id,
                "maxResults": min(_MAX_IDS_PER_REQUEST, remaining),
            }
            if page_token:
                params["pageToken"] = page_token
            payload = self._get("playlistItems", params)
            items = _items(payload)
            logger.info(
                "youtube.playlist.page playlist_id=%s page=%s items=%s collected=%s limit=%s",
                uploads_playlist_id,
                page,
                len(items),
                len(video_ids),
                limit,
            )
            if not items:
                break
            for item in items:
                if not isinstance(item, dict):
                    continue
                details = item.get("contentDetails")
                video_id = details.get("videoId") if isinstance(details, dict) else None
                if not isinstance(video_id, str) or not video_id.strip():
                    logger.warning("youtube.playlist.item_missing_video_id page=%s", page)
                    continue
                if video_id not in video_ids:
                    video_ids.append(video_id)
                if len(video_ids) >= limit:
                    break
            page_token = payload.get("nextPageToken")
            if not page_token or len(video_ids) >= limit:
                break
        return video_ids[:limit]

    def list_videos(self, video_ids: Sequence[str]) -> list[VideoResource]:
        resources: list[VideoResource] = []
        unique_ids = list(dict.fromkeys(video_ids))
        for chunk in _chunks(unique_ids, _MAX_IDS_PER_REQUEST):
            payload = self._get(
                "videos",
                {
                    "part": "snippet,contentDetails,statistics",
                    "id": ",".join(chunk),
                    "maxResults": _MAX_IDS_PER_REQUEST,
                },
            )
            for raw in _items(payload):
                try:
                    resources.append(VideoResource.model_validate(raw))
                except ValidationError:
                    logger.warning("youtube.video.invalid_resource skipped malformed item")
        logger.info("youtube.videos.listed requested=%s returned=%s", len(unique_ids), len(resources))
        return resources

    def list_video_categories(self, region_code: str) -> list[VideoCategoryResource]:
        payload = self._get(
            "videoCategories",
            {
                "part": "snippet",
                "regionCode": region_code,
            },
        )
        resources: list[VideoCategoryResource] = []
        for raw in _items(payload):
            try:
                resources.append(VideoCategoryResource.model_validate(raw))
            except ValidationError:
                logger.warning("youtube.video_category.invalid_resource skipped malformed item")
        logger.info(
            "youtube.video_categories.listed region=%s returned=%s",
            region_code,
            len(resources),
        )
        return resources

    def list_most_popular_videos(self, region_code: str, *, max_videos: int) -> list[VideoResource]:
        if max_videos < 1:
            return []
        resources: list[VideoResource] = []
        seen_ids: set[str] = set()
        page_token: str | None = None
        page = 0
        while len(resources) < max_videos:
            page += 1
            remaining = max_videos - len(resources)
            params: dict[str, str | int] = {
                "part": "snippet,contentDetails,statistics",
                "chart": "mostPopular",
                "regionCode": region_code,
                "maxResults": min(_MAX_IDS_PER_REQUEST, remaining),
            }
            if page_token:
                params["pageToken"] = page_token
            payload = self._get("videos", params)
            items = _items(payload)
            logger.info(
                "youtube.most_popular.page region=%s page=%s items=%s collected=%s limit=%s",
                region_code,
                page,
                len(items),
                len(resources),
                max_videos,
            )
            if not items:
                break
            for raw in items:
                try:
                    video = VideoResource.model_validate(raw)
                except ValidationError:
                    logger.warning("youtube.most_popular.invalid_resource skipped malformed item")
                    continue
                if video.id in seen_ids:
                    continue
                seen_ids.add(video.id)
                resources.append(video)
                if len(resources) >= max_videos:
                    break
            page_token = payload.get("nextPageToken")
            if not page_token or len(resources) >= max_videos:
                break
        return resources[:max_videos]

    def _get(self, endpoint: str, params: Mapping[str, str | int]) -> dict[str, Any]:
        query = {**params, "key": self._api_key}
        url = f"{YOUTUBE_API_BASE}/{endpoint}"
        logger.info("youtube.api.request endpoint=%s", endpoint)
        try:
            response = self._http.get(url, params=query)
        except httpx.HTTPError as exc:
            logger.exception("youtube.api.http_failure endpoint=%s error_type=%s", endpoint, type(exc).__name__)
            raise YouTubeHttpError(f"YouTube HTTP request failed for {endpoint}") from exc

        payload: dict[str, Any] | None
        try:
            decoded = response.json()
        except ValueError:
            decoded = None

        if response.status_code >= 400:
            raise _api_error_from_response(endpoint, response.status_code, decoded)

        if not isinstance(decoded, dict):
            raise YouTubeResponseError(f"YouTube {endpoint} returned non-object JSON")
        if "error" in decoded:
            raise _api_error_from_payload(endpoint, response.status_code, decoded)
        return decoded


def _items(payload: Mapping[str, Any]) -> list[Any]:
    items = payload.get("items")
    if items is None:
        return []
    if not isinstance(items, list):
        raise YouTubeResponseError("YouTube response 'items' was not a list")
    return items


def _chunks(values: Sequence[str], size: int) -> list[Sequence[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _api_error_from_response(endpoint: str, status_code: int, decoded: object) -> YouTubeApiError:
    if isinstance(decoded, dict) and "error" in decoded:
        return _api_error_from_payload(endpoint, status_code, decoded)
    logger.error("youtube.api.http_error endpoint=%s status=%s", endpoint, status_code)
    return YouTubeApiError(
        f"YouTube {endpoint} failed with HTTP {status_code}",
        status_code=status_code,
    )


def _api_error_from_payload(endpoint: str, status_code: int, payload: Mapping[str, Any]) -> YouTubeApiError:
    error = payload.get("error")
    message = "YouTube API error"
    reason: str | None = None
    if isinstance(error, dict):
        raw_message = error.get("message")
        if isinstance(raw_message, str) and raw_message.strip():
            message = raw_message.strip()
        errors = error.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict) and isinstance(first.get("reason"), str):
                reason = first["reason"]
        code = error.get("code")
        if isinstance(code, int):
            status_code = code
    logger.error(
        "youtube.api.error endpoint=%s status=%s reason=%s",
        endpoint,
        status_code,
        reason,
    )
    suffix = f" ({reason})" if reason else ""
    return YouTubeApiError(
        f"YouTube {endpoint} error{suffix}: {message}",
        status_code=status_code,
        reason=reason,
    )
