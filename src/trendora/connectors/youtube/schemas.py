"""Typed YouTube Data API v3 resource shapes used after JSON decode.

These models validate structure. Per-metric numeric parsing happens in the
normalizer so one bad statistic does not drop an entire channel or video.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _IgnoreExtra(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class ChannelSnippet(_IgnoreExtra):
    title: str | None = None
    description: str | None = None
    custom_url: str | None = Field(default=None, alias="customUrl")
    published_at: str | None = Field(default=None, alias="publishedAt")
    country: str | None = None


class RelatedPlaylists(_IgnoreExtra):
    uploads: str | None = None


class ChannelContentDetails(_IgnoreExtra):
    related_playlists: RelatedPlaylists | None = Field(default=None, alias="relatedPlaylists")


class ChannelResource(_IgnoreExtra):
    id: str
    snippet: ChannelSnippet = Field(default_factory=ChannelSnippet)
    content_details: ChannelContentDetails | None = Field(default=None, alias="contentDetails")
    statistics: dict[str, Any] = Field(default_factory=dict)

    @property
    def uploads_playlist_id(self) -> str | None:
        details = self.content_details
        if details is None or details.related_playlists is None:
            return None
        uploads = details.related_playlists.uploads
        if uploads is None:
            return None
        uploads = uploads.strip()
        return uploads or None


class VideoSnippet(_IgnoreExtra):
    title: str | None = None
    description: str | None = None
    channel_id: str | None = Field(default=None, alias="channelId")
    published_at: str | None = Field(default=None, alias="publishedAt")
    category_id: str | None = Field(default=None, alias="categoryId")
    tags: list[str] | None = None
    default_language: str | None = Field(default=None, alias="defaultLanguage")
    default_audio_language: str | None = Field(default=None, alias="defaultAudioLanguage")


class VideoContentDetails(_IgnoreExtra):
    duration: str | None = None
    definition: str | None = None
    caption: str | None = None


class VideoResource(_IgnoreExtra):
    id: str
    snippet: VideoSnippet = Field(default_factory=VideoSnippet)
    content_details: VideoContentDetails | None = Field(default=None, alias="contentDetails")
    statistics: dict[str, Any] = Field(default_factory=dict)


class VideoCategorySnippet(_IgnoreExtra):
    title: str | None = None


class VideoCategoryResource(_IgnoreExtra):
    id: str
    snippet: VideoCategorySnippet = Field(default_factory=VideoCategorySnippet)
