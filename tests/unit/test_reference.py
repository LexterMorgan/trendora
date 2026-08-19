"""Reference data used by the initial migration."""

from trendora.reference import MARKETS, RETENTION_POLICIES, SOURCES, TOPICS


def test_primary_markets_are_seeded() -> None:
    assert {row["code"] for row in MARKETS} == {"ID", "TH", "MY", "SG", "VN", "PH"}


def test_v1_sources_match_research_doc() -> None:
    codes = {row["code"] for row in SOURCES}
    assert codes == {
        "youtube",
        "hacker_news",
        "stack_exchange",
        "github",
        "wikimedia",
        "gdelt",
    }
    assert all(row["classification"] == "approved_mvp" for row in SOURCES)


def test_youtube_retention_hooks_are_thirty_days() -> None:
    policies = {row["code"]: row for row in RETENTION_POLICIES}
    assert policies["youtube_non_authorized_stats"]["retention_days"] == 30
    assert policies["youtube_non_authorized_metadata"]["retention_days"] == 30


def test_topic_taxonomy_covers_product_domain() -> None:
    codes = {row["code"] for row in TOPICS}
    assert "ai_education" in codes
    assert "programming" in codes
    assert "scholarships" in codes
