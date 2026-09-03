"""Facebook post normalization tests (M25B). Pure, deterministic, no network."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from trendora.connectors.facebook import normalize_facebook_posts
from trendora.connectors.facebook.exceptions import (
    FacebookConfigurationError,
    FacebookResponseError,
)
from trendora.connectors.facebook.schemas import FacebookPostResource
from trendora.research import (
    AnalysisBasis,
    EvidenceField,
    EvidencePack,
    FactCitation,
    ReferenceId,
    analyze_reference,
    interpretation_analysis_basis,
    reference_id,
)

UTC = timezone.utc
COLLECTED = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _post(
    post_id: str = "p1",
    *,
    message: str | None = "hello post",
    created: str | None = "2026-08-10T08:00:00+0000",
    permalink: str | None = "https://www.facebook.com/p/p1",
    shares: int | None = 3,
    reactions: int | None = 12,
    comments: int | None = 4,
) -> FacebookPostResource:
    return FacebookPostResource.model_validate(
        {
            "id": post_id,
            "message": message,
            "created_time": created,
            "permalink_url": permalink,
            "from": {"id": "page1", "name": "Example Page"},
            "shares": {"count": shares},
            "reactions": {"summary": {"total_count": reactions}},
            "comments": {"summary": {"total_count": comments}},
        }
    )


class TestMapping:
    def test_field_mapping_and_stable_ranks(self) -> None:
        refs = normalize_facebook_posts(
            [_post("p1"), _post("p2")], collected_at=COLLECTED
        )
        first, second = refs
        assert first.source_code == "facebook"
        assert first.content_external_id == "p1"
        assert first.url == "https://www.facebook.com/p/p1"
        assert first.title is None
        assert first.description == "hello post"
        assert first.published_at == datetime(2026, 8, 10, 8, 0, tzinfo=UTC)
        assert first.source_rank == 1
        assert second.source_rank == 2
        assert second.content_external_id == "p2"
        assert first.collected_at == COLLECTED

    def test_counts_mapped_zero_vs_missing(self) -> None:
        full = normalize_facebook_posts([_post("p1")], collected_at=COLLECTED)[0]
        assert full.metrics.reaction_count == 12
        assert full.metrics.comment_count == 4
        assert full.metrics.share_count == 3

        sparse = normalize_facebook_posts(
            [_post("p2", shares=None, reactions=None, comments=None)],
            collected_at=COLLECTED,
        )[0]
        assert sparse.metrics.reaction_count is None
        assert sparse.metrics.comment_count is None
        assert sparse.metrics.share_count is None

        zero = normalize_facebook_posts(
            [_post("p3", shares=0, reactions=0, comments=0)],
            collected_at=COLLECTED,
        )[0]
        assert zero.metrics.share_count == 0
        assert zero.metrics.reaction_count == 0
        assert zero.metrics.comment_count == 0

    def test_reactions_never_populate_like_count(self) -> None:
        ref = normalize_facebook_posts([_post("p1")], collected_at=COLLECTED)[0]
        assert ref.metrics.like_count is None
        assert ref.metrics.reaction_count == 12

    def test_message_description_and_no_fabricated_title(self) -> None:
        ref = normalize_facebook_posts(
            [_post("p1", message="exact  source text")], collected_at=COLLECTED
        )[0]
        assert ref.description == "exact  source text"
        assert ref.title is None

    def test_market_and_channel_fields_none(self) -> None:
        ref = normalize_facebook_posts([_post("p1")], collected_at=COLLECTED)[0]
        assert ref.market_context is None
        assert ref.market_basis is None
        assert ref.channel_external_id is None
        assert ref.channel_title is None

    def test_utc_and_offset_timestamps_parse_aware(self) -> None:
        utc_z = normalize_facebook_posts(
            [_post("p1", created="2026-08-10T08:00:00Z")], collected_at=COLLECTED
        )[0]
        assert utc_z.published_at == datetime(2026, 8, 10, 8, 0, tzinfo=UTC)

        offset = normalize_facebook_posts(
            [_post("p2", created="2026-08-10T09:00:00+01:00")], collected_at=COLLECTED
        )[0]
        assert offset.published_at == datetime(2026, 8, 10, 8, 0, tzinfo=UTC)

    def test_missing_timestamp_stays_none(self) -> None:
        ref = normalize_facebook_posts(
            [_post("p1", created=None)], collected_at=COLLECTED
        )[0]
        assert ref.published_at is None


class TestFailClosed:
    def test_naive_collected_at_rejected(self) -> None:
        with pytest.raises(FacebookConfigurationError):
            normalize_facebook_posts(
                [_post("p1")], collected_at=datetime(2026, 8, 1, 12, 0)
            )

    def test_blank_post_id_rejected(self) -> None:
        with pytest.raises(FacebookResponseError, match="blank"):
            normalize_facebook_posts([_post(" ")], collected_at=COLLECTED)

    def test_duplicate_post_ids_rejected(self) -> None:
        with pytest.raises(FacebookResponseError, match="duplicate"):
            normalize_facebook_posts(
                [_post("p1"), _post("p1")], collected_at=COLLECTED
            )

    def test_missing_or_unsafe_url_rejected(self) -> None:
        for url in (None, "", "javascript:alert(1)", "ftp://x", "www.facebook.com/x"):
            with pytest.raises(FacebookResponseError):
                normalize_facebook_posts(
                    [_post("p1", permalink=url)], collected_at=COLLECTED
                )

    def test_malformed_or_hostless_urls_rejected(self) -> None:
        for url in ("https://", "http:///post", "http://a b.com/permal"):
            with pytest.raises(FacebookResponseError):
                normalize_facebook_posts(
                    [_post("p1", permalink=url)], collected_at=COLLECTED
                )

    def test_non_facebook_http_urls_accepted(self) -> None:
        for url in ("https://example.com/post", "http://other.example/x"):
            ref = normalize_facebook_posts(
                [_post("p1", permalink=url)], collected_at=COLLECTED
            )[0]
            assert ref.url == url

    def test_malformed_created_time_rejected(self) -> None:
        with pytest.raises(FacebookResponseError, match="malformed"):
            normalize_facebook_posts(
                [_post("p1", created="not-a-date")], collected_at=COLLECTED
            )

    def test_naive_created_time_rejected(self) -> None:
        with pytest.raises(FacebookResponseError, match="timezone-aware"):
            normalize_facebook_posts(
                [_post("p1", created="2026-08-10T08:00:00")], collected_at=COLLECTED
            )


class TestEvidenceIntegration:
    def test_facebook_reaction_and_share_facts_appear(self) -> None:
        ref = normalize_facebook_posts(
            [_post("p1")], collected_at=COLLECTED
        )[0]
        analysis = analyze_reference(ref)
        assert reference_id(ref) == ReferenceId("facebook", "p1")
        fields = {fact.field for fact in analysis.facts}
        assert EvidenceField.REACTION_COUNT in fields
        assert EvidenceField.SHARE_COUNT in fields
        assert EvidenceField.COMMENT_COUNT in fields
        assert EvidenceField.VIEW_COUNT in fields
        assert EvidenceField.LIKE_COUNT in fields
        reaction = next(
            fact for fact in analysis.facts if fact.field is EvidenceField.REACTION_COUNT
        )
        assert reaction.value == 12

    def test_reaction_share_citation_basis_is_raw_metrics(self) -> None:
        ref = normalize_facebook_posts(
            [_post("p1")], collected_at=COLLECTED
        )[0]
        pack = EvidencePack(analyses=(analyze_reference(ref),))
        identity = reference_id(ref)
        for field in (EvidenceField.REACTION_COUNT, EvidenceField.SHARE_COUNT):
            citation = FactCitation(reference=identity, field=field)
            assert interpretation_analysis_basis(pack, citation) is AnalysisBasis.RAW_METRICS
