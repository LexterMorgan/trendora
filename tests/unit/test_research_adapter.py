"""M35A contract-adapter tests. Pure, no network, no database."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from trendora.research.adapter import (
    DEFAULT_MARKETS,
    DEFAULT_SIMPLIFIED_SOURCES,
    adapt_research_request,
)
from trendora.research.exceptions import ResearchValidationError

TODAY = date.today()


class TestSimplifiedContract:
    def test_only_topic_is_global_across_both_sources(self):
        query = adapt_research_request({"topic": "AI education"})
        assert query.topic == "AI education"
        # Global: no explicit country restriction.
        assert query.markets == ()
        assert query.market is None
        assert query.source_codes == ("youtube", "public_web")
        assert query.result_limit == 50
        assert query.date_to == TODAY
        assert query.date_from == TODAY - timedelta(days=29)

    def test_default_markets_constant_is_empty_global(self):
        assert DEFAULT_MARKETS == ()

    def test_default_simplified_sources_constant(self):
        assert DEFAULT_SIMPLIFIED_SOURCES == ("youtube", "public_web")

    def test_topic_is_stripped(self):
        query = adapt_research_request({"topic": "  spaced  "})
        assert query.topic == "spaced"


class TestFullContract:
    def test_full_contract_unchanged(self):
        request = {
            "topic": "AI education",
            "markets": ["ID", "TH"],
            "date_from": date(2026, 8, 1),
            "date_to": date(2026, 8, 31),
            "sources": ["youtube"],
            "result_limit": 30,
        }
        query = adapt_research_request(request)
        assert query.markets == ("ID", "TH")
        assert query.date_from == date(2026, 8, 1)
        assert query.date_to == date(2026, 8, 31)
        assert query.result_limit == 30
        assert query.market is None

    def test_legacy_singular_market_preserved(self):
        query = adapt_research_request(
            {
                "topic": "t",
                "market": "sg",
                "date_from": date(2026, 8, 1),
                "date_to": date(2026, 8, 31),
            }
        )
        assert query.markets == ("SG",)
        assert query.market == "SG"


class TestPartialContract:
    def test_provided_and_default_fields_mix(self):
        query = adapt_research_request({"topic": "t", "result_limit": 10})
        assert query.result_limit == 10
        # No market supplied → global, still both sources.
        assert query.markets == ()
        assert query.date_to == TODAY

    def test_explicit_markets_with_default_dates_is_regional(self):
        query = adapt_research_request({"topic": "t", "markets": ["SG", "ID"]})
        assert query.markets == ("SG", "ID")
        assert query.market is None
        assert query.date_to == TODAY

    def test_explicit_market_keeps_regional_default_source(self):
        query = adapt_research_request({"topic": "t", "market": "TH"})
        assert query.markets == ("TH",)
        assert query.market == "TH"
        assert query.source_codes == ("youtube",)

    def test_sources_override(self):
        query = adapt_research_request(
            {"topic": "t", "sources": ["facebook"], "facebook_page_id": "page1"}
        )
        assert query.source_codes == ("facebook",)


class TestValidationPreserved:
    def test_missing_topic_rejected(self):
        with pytest.raises(ResearchValidationError, match="topic"):
            adapt_research_request({})

    def test_blank_topic_rejected(self):
        with pytest.raises(ResearchValidationError, match="topic"):
            adapt_research_request({"topic": "   "})

    def test_unsupported_market_rejected(self):
        with pytest.raises(ResearchValidationError, match="unsupported"):
            adapt_research_request({"topic": "t", "markets": ["US"]})

    def test_both_market_and_markets_rejected(self):
        with pytest.raises(ResearchValidationError, match="not both"):
            adapt_research_request(
                {"topic": "t", "market": "SG", "markets": ["SG", "ID"]}
            )

    def test_no_market_with_explicit_dates_is_global(self):
        # Explicit dates without a market are a valid global request now.
        query = adapt_research_request(
            {
                "topic": "t",
                "date_from": date(2026, 8, 1),
                "date_to": date(2026, 8, 31),
            }
        )
        assert query.markets == ()
        assert query.market is None
        assert query.date_from == date(2026, 8, 1)
        assert query.date_to == date(2026, 8, 31)
        assert query.source_codes == ("youtube", "public_web")

    def test_invalid_result_limit_rejected(self):
        with pytest.raises(ResearchValidationError):
            adapt_research_request({"topic": "t", "result_limit": 0})

    def test_reversed_date_window_rejected(self):
        with pytest.raises(ResearchValidationError):
            adapt_research_request(
                {
                    "topic": "t",
                    "markets": ["SG"],
                    "date_from": date(2026, 8, 31),
                    "date_to": date(2026, 8, 1),
                }
            )

    def test_partial_date_window_defaults_missing_side(self):
        query = adapt_research_request(
            {"topic": "t", "markets": ["SG"], "date_from": date(2026, 8, 1)}
        )
        assert query.date_from == date(2026, 8, 1)
        assert query.date_to == TODAY
