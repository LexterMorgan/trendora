"""Hacker News normalization tests. No HTTP and no database."""

from datetime import datetime, timezone

import pytest

from trendora.connectors.hackernews.exceptions import HackerNewsItemError
from trendora.connectors.hackernews.normalizer import normalize_story
from trendora.connectors.hackernews.schemas import ItemResource
from tests.fixtures.hackernews_responses import (
    COMMENT_ITEM,
    DEAD_ITEM,
    DELETED_ITEM,
    STORY_A,
    STORY_A_ID,
    STORY_B,
    STORY_C,
)

COLLECTED = datetime(2026, 8, 20, 18, 0, tzinfo=timezone.utc)


def test_valid_story_normalization() -> None:
    item = ItemResource.model_validate(STORY_A)
    story = normalize_story(item, feeds=("topstories", "beststories"), collected_at=COLLECTED)
    assert story.external_id == str(STORY_A_ID)
    assert story.content_type == "story"
    assert story.title == "Example AI education tool"
    assert story.url == "https://example.com/ai-edu"
    assert story.published_at == datetime(2007, 4, 4, 19, 16, 40, tzinfo=timezone.utc)
    assert story.published_at is not None and story.published_at.tzinfo is not None
    assert story.source_metadata["hn_type"] == "story"
    assert story.source_metadata["author"] == "alice"
    assert story.source_metadata["feeds"] == ["topstories", "beststories"]
    assert story.source_metadata["url"] == "https://example.com/ai-edu"
    metrics = {row.metric_name: row.metric_value for row in story.snapshots}
    assert metrics == {"score": 120, "comment_count": 15}
    assert all(row.collected_at == COLLECTED for row in story.snapshots)
    assert all(row.subject == "content_item" for row in story.snapshots)


def test_text_only_story_uses_hn_item_url_and_description() -> None:
    item = ItemResource.model_validate(STORY_B)
    story = normalize_story(item, feeds=("newstories",), collected_at=COLLECTED)
    assert story.url == f"https://news.ycombinator.com/item?id={STORY_B['id']}"
    assert story.description == "Ask HN: how do you teach Python?"
    assert story.source_metadata["text"] == "Ask HN: how do you teach Python?"
    metrics = {row.metric_name: row.metric_value for row in story.snapshots}
    assert metrics == {"score": 8, "comment_count": 0}


def test_missing_descendants_skips_comment_count() -> None:
    item = ItemResource.model_validate(STORY_C)
    story = normalize_story(item, feeds=("topstories",), collected_at=COLLECTED)
    assert {row.metric_name for row in story.snapshots} == {"score"}


def test_deleted_dead_and_non_story_are_rejected() -> None:
    with pytest.raises(HackerNewsItemError, match="deleted"):
        normalize_story(
            ItemResource.model_validate(DELETED_ITEM),
            feeds=("topstories",),
            collected_at=COLLECTED,
        )
    with pytest.raises(HackerNewsItemError, match="dead"):
        normalize_story(
            ItemResource.model_validate(DEAD_ITEM),
            feeds=("topstories",),
            collected_at=COLLECTED,
        )
    with pytest.raises(HackerNewsItemError, match="story"):
        normalize_story(
            ItemResource.model_validate(COMMENT_ITEM),
            feeds=("topstories",),
            collected_at=COLLECTED,
        )


def test_naive_collected_at_is_rejected() -> None:
    item = ItemResource.model_validate(STORY_A)
    with pytest.raises(ValueError, match="timezone-aware"):
        normalize_story(item, feeds=("topstories",), collected_at=datetime(2026, 8, 20))
