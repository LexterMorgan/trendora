"""Synthetic analytics observations. Not live API data."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from trendora.analytics.models import MetricObservation, SubjectKind
from trendora.models import ContentItem, MetricSnapshot, Publisher
from trendora.reference import MARKET_IDS, SOURCE_IDS

T10 = datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc)
T12 = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
T15 = datetime(2026, 8, 21, 15, 0, tzinfo=timezone.utc)
C12_EARLY = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
C12_LATE = datetime(2026, 8, 21, 12, 5, tzinfo=timezone.utc)

YT_VIDEO_ID = UUID("55555555-5555-4555-8555-555555555501")
YT_CHANNEL_ID = UUID("55555555-5555-4555-8555-555555555502")
HN_STORY_ID = UUID("55555555-5555-4555-8555-555555555503")
SE_QUESTION_ID = UUID("55555555-5555-4555-8555-555555555504")
GH_REPO_ID = UUID("55555555-5555-4555-8555-555555555505")

YT_VIDEO_EXT = "m5fixture-video-1"
YT_CHANNEL_EXT = "UCm5fixture000000000000001"
HN_STORY_EXT = "m5fixture-story-1"
SE_QUESTION_EXT = "m5fixture-stackoverflow:1"
GH_REPO_EXT = "m5fixture/repo"

SNAP_YT_VIEW_T10 = UUID("55555555-5555-4555-8555-555555555511")
SNAP_YT_VIEW_T12 = UUID("55555555-5555-4555-8555-555555555512")
SNAP_YT_VIEW_T15 = UUID("55555555-5555-4555-8555-555555555513")
SNAP_YT_LIKE_T10 = UUID("55555555-5555-4555-8555-555555555514")
SNAP_YT_LIKE_T15 = UUID("55555555-5555-4555-8555-555555555515")
SNAP_YT_COMMENT_T10 = UUID("55555555-5555-4555-8555-555555555516")
SNAP_YT_SUB_T10 = UUID("55555555-5555-4555-8555-555555555517")
SNAP_YT_SUB_T15 = UUID("55555555-5555-4555-8555-555555555518")
SNAP_HN_SCORE_T12_A = UUID("55555555-5555-4555-8555-555555555521")
SNAP_HN_SCORE_T12_B = UUID("55555555-5555-4555-8555-555555555522")
SNAP_HN_COMMENTS_T10 = UUID("55555555-5555-4555-8555-555555555523")
SNAP_SE_SCORE_T10 = UUID("55555555-5555-4555-8555-555555555531")
SNAP_SE_VIEW_T10 = UUID("55555555-5555-4555-8555-555555555532")
SNAP_SE_ANSWER_T10 = UUID("55555555-5555-4555-8555-555555555533")
SNAP_GH_STAR_T10 = UUID("55555555-5555-4555-8555-555555555541")
SNAP_GH_FORK_T10 = UUID("55555555-5555-4555-8555-555555555542")
SNAP_GH_ISSUE_T10 = UUID("55555555-5555-4555-8555-555555555543")
SNAP_GH_WATCH_T10 = UUID("55555555-5555-4555-8555-555555555544")


def _obs(**kwargs) -> MetricObservation:
    return MetricObservation(**kwargs)


GOLDEN_OBSERVATIONS: tuple[MetricObservation, ...] = (
    _obs(
        snapshot_id=SNAP_YT_VIEW_T10,
        source_code="youtube",
        source_id=SOURCE_IDS["youtube"],
        metric_name="view_count",
        metric_value=100,
        observed_at=T10,
        collected_at=T10,
        subject_kind=SubjectKind.CONTENT_ITEM,
        content_item_id=YT_VIDEO_ID,
        content_external_id=YT_VIDEO_EXT,
        content_type="video",
        publisher_id=YT_CHANNEL_ID,
        publisher_external_id=YT_CHANNEL_EXT,
        market_id=MARKET_IDS["ID"],
        market_code="ID",
    ),
    _obs(
        snapshot_id=SNAP_YT_VIEW_T12,
        source_code="youtube",
        source_id=SOURCE_IDS["youtube"],
        metric_name="view_count",
        metric_value=150,
        observed_at=T12,
        collected_at=T12,
        subject_kind=SubjectKind.CONTENT_ITEM,
        content_item_id=YT_VIDEO_ID,
        content_external_id=YT_VIDEO_EXT,
        content_type="video",
        publisher_id=YT_CHANNEL_ID,
        publisher_external_id=YT_CHANNEL_EXT,
        market_id=MARKET_IDS["ID"],
        market_code="ID",
    ),
    _obs(
        snapshot_id=SNAP_YT_VIEW_T15,
        source_code="youtube",
        source_id=SOURCE_IDS["youtube"],
        metric_name="view_count",
        metric_value=200,
        observed_at=T15,
        collected_at=T15,
        subject_kind=SubjectKind.CONTENT_ITEM,
        content_item_id=YT_VIDEO_ID,
        content_external_id=YT_VIDEO_EXT,
        content_type="video",
        publisher_id=YT_CHANNEL_ID,
        publisher_external_id=YT_CHANNEL_EXT,
        market_id=MARKET_IDS["ID"],
        market_code="ID",
    ),
    _obs(
        snapshot_id=SNAP_YT_LIKE_T10,
        source_code="youtube",
        source_id=SOURCE_IDS["youtube"],
        metric_name="like_count",
        metric_value=1,
        observed_at=T10,
        collected_at=T10,
        subject_kind=SubjectKind.CONTENT_ITEM,
        content_item_id=YT_VIDEO_ID,
        content_external_id=YT_VIDEO_EXT,
        content_type="video",
        publisher_id=YT_CHANNEL_ID,
        publisher_external_id=YT_CHANNEL_EXT,
        market_id=MARKET_IDS["ID"],
        market_code="ID",
    ),
    _obs(
        snapshot_id=SNAP_YT_LIKE_T15,
        source_code="youtube",
        source_id=SOURCE_IDS["youtube"],
        metric_name="like_count",
        metric_value=3,
        observed_at=T15,
        collected_at=T15,
        subject_kind=SubjectKind.CONTENT_ITEM,
        content_item_id=YT_VIDEO_ID,
        content_external_id=YT_VIDEO_EXT,
        content_type="video",
        publisher_id=YT_CHANNEL_ID,
        publisher_external_id=YT_CHANNEL_EXT,
        market_id=MARKET_IDS["ID"],
        market_code="ID",
    ),
    _obs(
        snapshot_id=SNAP_YT_COMMENT_T10,
        source_code="youtube",
        source_id=SOURCE_IDS["youtube"],
        metric_name="comment_count",
        metric_value=2,
        observed_at=T10,
        collected_at=T10,
        subject_kind=SubjectKind.CONTENT_ITEM,
        content_item_id=YT_VIDEO_ID,
        content_external_id=YT_VIDEO_EXT,
        content_type="video",
        publisher_id=YT_CHANNEL_ID,
        publisher_external_id=YT_CHANNEL_EXT,
        market_id=MARKET_IDS["ID"],
        market_code="ID",
    ),
    _obs(
        snapshot_id=SNAP_YT_SUB_T10,
        source_code="youtube",
        source_id=SOURCE_IDS["youtube"],
        metric_name="subscriber_count",
        metric_value=50,
        observed_at=T10,
        collected_at=T10,
        subject_kind=SubjectKind.PUBLISHER,
        publisher_id=YT_CHANNEL_ID,
        publisher_external_id=YT_CHANNEL_EXT,
        market_id=MARKET_IDS["ID"],
        market_code="ID",
    ),
    _obs(
        snapshot_id=SNAP_YT_SUB_T15,
        source_code="youtube",
        source_id=SOURCE_IDS["youtube"],
        metric_name="subscriber_count",
        metric_value=60,
        observed_at=T15,
        collected_at=T15,
        subject_kind=SubjectKind.PUBLISHER,
        publisher_id=YT_CHANNEL_ID,
        publisher_external_id=YT_CHANNEL_EXT,
        market_id=MARKET_IDS["ID"],
        market_code="ID",
    ),
    _obs(
        snapshot_id=SNAP_HN_SCORE_T12_A,
        source_code="hacker_news",
        source_id=SOURCE_IDS["hacker_news"],
        metric_name="score",
        metric_value=10,
        observed_at=T12,
        collected_at=C12_EARLY,
        subject_kind=SubjectKind.CONTENT_ITEM,
        content_item_id=HN_STORY_ID,
        content_external_id=HN_STORY_EXT,
        content_type="story",
        market_id=None,
        market_code=None,
    ),
    _obs(
        snapshot_id=SNAP_HN_SCORE_T12_B,
        source_code="hacker_news",
        source_id=SOURCE_IDS["hacker_news"],
        metric_name="score",
        metric_value=12,
        observed_at=T12,
        collected_at=C12_LATE,
        subject_kind=SubjectKind.CONTENT_ITEM,
        content_item_id=HN_STORY_ID,
        content_external_id=HN_STORY_EXT,
        content_type="story",
        market_id=None,
        market_code=None,
    ),
    _obs(
        snapshot_id=SNAP_HN_COMMENTS_T10,
        source_code="hacker_news",
        source_id=SOURCE_IDS["hacker_news"],
        metric_name="comment_count",
        metric_value=4,
        observed_at=T10,
        collected_at=T10,
        subject_kind=SubjectKind.CONTENT_ITEM,
        content_item_id=HN_STORY_ID,
        content_external_id=HN_STORY_EXT,
        content_type="story",
        market_id=None,
        market_code=None,
    ),
    _obs(
        snapshot_id=SNAP_SE_SCORE_T10,
        source_code="stack_exchange",
        source_id=SOURCE_IDS["stack_exchange"],
        metric_name="score",
        metric_value=7,
        observed_at=T10,
        collected_at=T10,
        subject_kind=SubjectKind.CONTENT_ITEM,
        content_item_id=SE_QUESTION_ID,
        content_external_id=SE_QUESTION_EXT,
        content_type="question",
        market_id=None,
        market_code=None,
    ),
    _obs(
        snapshot_id=SNAP_SE_VIEW_T10,
        source_code="stack_exchange",
        source_id=SOURCE_IDS["stack_exchange"],
        metric_name="view_count",
        metric_value=90,
        observed_at=T10,
        collected_at=T10,
        subject_kind=SubjectKind.CONTENT_ITEM,
        content_item_id=SE_QUESTION_ID,
        content_external_id=SE_QUESTION_EXT,
        content_type="question",
        market_id=None,
        market_code=None,
    ),
    _obs(
        snapshot_id=SNAP_SE_ANSWER_T10,
        source_code="stack_exchange",
        source_id=SOURCE_IDS["stack_exchange"],
        metric_name="answer_count",
        metric_value=2,
        observed_at=T10,
        collected_at=T10,
        subject_kind=SubjectKind.CONTENT_ITEM,
        content_item_id=SE_QUESTION_ID,
        content_external_id=SE_QUESTION_EXT,
        content_type="question",
        market_id=None,
        market_code=None,
    ),
    _obs(
        snapshot_id=SNAP_GH_STAR_T10,
        source_code="github",
        source_id=SOURCE_IDS["github"],
        metric_name="stargazer_count",
        metric_value=11,
        observed_at=T10,
        collected_at=T10,
        subject_kind=SubjectKind.CONTENT_ITEM,
        content_item_id=GH_REPO_ID,
        content_external_id=GH_REPO_EXT,
        content_type="repository",
        market_id=None,
        market_code=None,
    ),
    _obs(
        snapshot_id=SNAP_GH_FORK_T10,
        source_code="github",
        source_id=SOURCE_IDS["github"],
        metric_name="fork_count",
        metric_value=3,
        observed_at=T10,
        collected_at=T10,
        subject_kind=SubjectKind.CONTENT_ITEM,
        content_item_id=GH_REPO_ID,
        content_external_id=GH_REPO_EXT,
        content_type="repository",
        market_id=None,
        market_code=None,
    ),
    _obs(
        snapshot_id=SNAP_GH_ISSUE_T10,
        source_code="github",
        source_id=SOURCE_IDS["github"],
        metric_name="open_issue_count",
        metric_value=1,
        observed_at=T10,
        collected_at=T10,
        subject_kind=SubjectKind.CONTENT_ITEM,
        content_item_id=GH_REPO_ID,
        content_external_id=GH_REPO_EXT,
        content_type="repository",
        market_id=None,
        market_code=None,
    ),
    _obs(
        snapshot_id=SNAP_GH_WATCH_T10,
        source_code="github",
        source_id=SOURCE_IDS["github"],
        metric_name="watcher_count",
        metric_value=5,
        observed_at=T10,
        collected_at=T10,
        subject_kind=SubjectKind.CONTENT_ITEM,
        content_item_id=GH_REPO_ID,
        content_external_id=GH_REPO_EXT,
        content_type="repository",
        market_id=None,
        market_code=None,
    ),
)


def seed_analytics_fixture(session: Session) -> None:
    """Insert golden fixture rows. Caller owns the transaction."""

    session.add(
        Publisher(
            id=YT_CHANNEL_ID,
            source_id=SOURCE_IDS["youtube"],
            external_id=YT_CHANNEL_EXT,
            name="M5 fixture channel",
            market_id=MARKET_IDS["ID"],
        )
    )
    session.add(
        ContentItem(
            id=YT_VIDEO_ID,
            source_id=SOURCE_IDS["youtube"],
            publisher_id=YT_CHANNEL_ID,
            external_id=YT_VIDEO_EXT,
            content_type="video",
            title="M5 fixture video",
            market_id=MARKET_IDS["ID"],
        )
    )
    session.add(
        ContentItem(
            id=HN_STORY_ID,
            source_id=SOURCE_IDS["hacker_news"],
            publisher_id=None,
            external_id=HN_STORY_EXT,
            content_type="story",
            title="M5 fixture story",
            market_id=None,
        )
    )
    session.add(
        ContentItem(
            id=SE_QUESTION_ID,
            source_id=SOURCE_IDS["stack_exchange"],
            publisher_id=None,
            external_id=SE_QUESTION_EXT,
            content_type="question",
            title="M5 fixture question",
            market_id=None,
        )
    )
    session.add(
        ContentItem(
            id=GH_REPO_ID,
            source_id=SOURCE_IDS["github"],
            publisher_id=None,
            external_id=GH_REPO_EXT,
            content_type="repository",
            title="M5 fixture repo",
            market_id=None,
        )
    )
    session.flush()

    def add_snap(
        snapshot_id: UUID,
        *,
        source_id: UUID,
        metric_name: str,
        metric_value: int,
        observed_at: datetime,
        collected_at: datetime,
        content_item_id: UUID | None = None,
        publisher_id: UUID | None = None,
    ) -> None:
        session.add(
            MetricSnapshot(
                id=snapshot_id,
                source_id=source_id,
                content_item_id=content_item_id,
                publisher_id=publisher_id,
                metric_name=metric_name,
                metric_value=metric_value,
                observed_at=observed_at,
                collected_at=collected_at,
            )
        )

    yt = SOURCE_IDS["youtube"]
    add_snap(SNAP_YT_VIEW_T10, source_id=yt, metric_name="view_count", metric_value=100, observed_at=T10, collected_at=T10, content_item_id=YT_VIDEO_ID)
    add_snap(SNAP_YT_VIEW_T12, source_id=yt, metric_name="view_count", metric_value=150, observed_at=T12, collected_at=T12, content_item_id=YT_VIDEO_ID)
    add_snap(SNAP_YT_VIEW_T15, source_id=yt, metric_name="view_count", metric_value=200, observed_at=T15, collected_at=T15, content_item_id=YT_VIDEO_ID)
    add_snap(SNAP_YT_LIKE_T10, source_id=yt, metric_name="like_count", metric_value=1, observed_at=T10, collected_at=T10, content_item_id=YT_VIDEO_ID)
    add_snap(SNAP_YT_LIKE_T15, source_id=yt, metric_name="like_count", metric_value=3, observed_at=T15, collected_at=T15, content_item_id=YT_VIDEO_ID)
    add_snap(SNAP_YT_COMMENT_T10, source_id=yt, metric_name="comment_count", metric_value=2, observed_at=T10, collected_at=T10, content_item_id=YT_VIDEO_ID)
    add_snap(SNAP_YT_SUB_T10, source_id=yt, metric_name="subscriber_count", metric_value=50, observed_at=T10, collected_at=T10, publisher_id=YT_CHANNEL_ID)
    add_snap(SNAP_YT_SUB_T15, source_id=yt, metric_name="subscriber_count", metric_value=60, observed_at=T15, collected_at=T15, publisher_id=YT_CHANNEL_ID)

    hn = SOURCE_IDS["hacker_news"]
    add_snap(SNAP_HN_SCORE_T12_A, source_id=hn, metric_name="score", metric_value=10, observed_at=T12, collected_at=C12_EARLY, content_item_id=HN_STORY_ID)
    add_snap(SNAP_HN_SCORE_T12_B, source_id=hn, metric_name="score", metric_value=12, observed_at=T12, collected_at=C12_LATE, content_item_id=HN_STORY_ID)
    add_snap(SNAP_HN_COMMENTS_T10, source_id=hn, metric_name="comment_count", metric_value=4, observed_at=T10, collected_at=T10, content_item_id=HN_STORY_ID)

    se = SOURCE_IDS["stack_exchange"]
    add_snap(SNAP_SE_SCORE_T10, source_id=se, metric_name="score", metric_value=7, observed_at=T10, collected_at=T10, content_item_id=SE_QUESTION_ID)
    add_snap(SNAP_SE_VIEW_T10, source_id=se, metric_name="view_count", metric_value=90, observed_at=T10, collected_at=T10, content_item_id=SE_QUESTION_ID)
    add_snap(SNAP_SE_ANSWER_T10, source_id=se, metric_name="answer_count", metric_value=2, observed_at=T10, collected_at=T10, content_item_id=SE_QUESTION_ID)

    gh = SOURCE_IDS["github"]
    add_snap(SNAP_GH_STAR_T10, source_id=gh, metric_name="stargazer_count", metric_value=11, observed_at=T10, collected_at=T10, content_item_id=GH_REPO_ID)
    add_snap(SNAP_GH_FORK_T10, source_id=gh, metric_name="fork_count", metric_value=3, observed_at=T10, collected_at=T10, content_item_id=GH_REPO_ID)
    add_snap(SNAP_GH_ISSUE_T10, source_id=gh, metric_name="open_issue_count", metric_value=1, observed_at=T10, collected_at=T10, content_item_id=GH_REPO_ID)
    add_snap(SNAP_GH_WATCH_T10, source_id=gh, metric_name="watcher_count", metric_value=5, observed_at=T10, collected_at=T10, content_item_id=GH_REPO_ID)
    session.flush()
