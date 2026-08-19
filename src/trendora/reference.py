"""Stable reference rows for V1 (markets, sources, retention hooks).

Values reflect the product brief and docs/03_DATA_SOURCES.md. This is not a
connector and does not fetch external data.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

# Fixed UUIDs keep seed data deterministic across environments.
MARKET_IDS: Final[dict[str, UUID]] = {
    "ID": UUID("11111111-1111-4111-8111-111111111111"),
    "TH": UUID("11111111-1111-4111-8111-111111111112"),
    "MY": UUID("11111111-1111-4111-8111-111111111113"),
    "SG": UUID("11111111-1111-4111-8111-111111111114"),
    "VN": UUID("11111111-1111-4111-8111-111111111115"),
    "PH": UUID("11111111-1111-4111-8111-111111111116"),
}

SOURCE_IDS: Final[dict[str, UUID]] = {
    "youtube": UUID("22222222-2222-4222-8222-222222222221"),
    "hacker_news": UUID("22222222-2222-4222-8222-222222222222"),
    "stack_exchange": UUID("22222222-2222-4222-8222-222222222223"),
    "github": UUID("22222222-2222-4222-8222-222222222224"),
    "wikimedia": UUID("22222222-2222-4222-8222-222222222225"),
    "gdelt": UUID("22222222-2222-4222-8222-222222222226"),
}

TOPIC_IDS: Final[dict[str, UUID]] = {
    "ai_education": UUID("33333333-3333-4333-8333-333333333331"),
    "technology_education": UUID("33333333-3333-4333-8333-333333333332"),
    "data_science": UUID("33333333-3333-4333-8333-333333333333"),
    "programming": UUID("33333333-3333-4333-8333-333333333334"),
    "digital_skills": UUID("33333333-3333-4333-8333-333333333335"),
    "stem": UUID("33333333-3333-4333-8333-333333333336"),
    "online_learning": UUID("33333333-3333-4333-8333-333333333337"),
    "scholarships": UUID("33333333-3333-4333-8333-333333333338"),
    "career_education": UUID("33333333-3333-4333-8333-333333333339"),
}

RETENTION_POLICY_IDS: Final[dict[str, UUID]] = {
    "youtube_non_authorized_stats": UUID("44444444-4444-4444-8444-444444444441"),
    "youtube_non_authorized_metadata": UUID("44444444-4444-4444-8444-444444444442"),
}

MARKETS: Final[tuple[dict[str, str], ...]] = (
    {"code": "ID", "name": "Indonesia"},
    {"code": "TH", "name": "Thailand"},
    {"code": "MY", "name": "Malaysia"},
    {"code": "SG", "name": "Singapore"},
    {"code": "VN", "name": "Vietnam"},
    {"code": "PH", "name": "Philippines"},
)

# classification values match docs/03_DATA_SOURCES.md labels.
SOURCES: Final[tuple[dict[str, str], ...]] = (
    {
        "code": "youtube",
        "name": "YouTube Data API v3",
        "classification": "approved_mvp",
        "notes": "Primary V1 social source. Public stats are snapshots; search.list is quota-limited.",
    },
    {
        "code": "hacker_news",
        "name": "Hacker News",
        "classification": "approved_mvp",
        "notes": "Supplementary global tech signal. Connector not implemented in Milestone 1.",
    },
    {
        "code": "stack_exchange",
        "name": "Stack Exchange",
        "classification": "approved_mvp",
        "notes": "Supplementary programming Q&A. Connector not implemented in Milestone 1.",
    },
    {
        "code": "github",
        "name": "GitHub REST API",
        "classification": "approved_mvp",
        "notes": "Supplementary public repository activity. Connector not implemented in Milestone 1.",
    },
    {
        "code": "wikimedia",
        "name": "Wikimedia Action API",
        "classification": "approved_mvp",
        "notes": "Context only, not social KPIs. Connector not implemented in Milestone 1.",
    },
    {
        "code": "gdelt",
        "name": "GDELT 2.0",
        "classification": "approved_mvp",
        "notes": "News/event context via HTTP files, not BigQuery. Connector not implemented in Milestone 1.",
    },
)

TOPICS: Final[tuple[dict[str, str], ...]] = (
    {"code": "ai_education", "name": "AI education"},
    {"code": "technology_education", "name": "Technology education"},
    {"code": "data_science", "name": "Data science"},
    {"code": "programming", "name": "Programming"},
    {"code": "digital_skills", "name": "Digital skills"},
    {"code": "stem", "name": "STEM"},
    {"code": "online_learning", "name": "Online learning"},
    {"code": "scholarships", "name": "Scholarships"},
    {"code": "career_education", "name": "Technology/career education"},
)

# Documented YouTube Developer Policies III.E.4 (see docs/03_DATA_SOURCES.md).
# Do not treat these rows as legal advice or as extra invented rules.
RETENTION_POLICIES: Final[tuple[dict[str, object], ...]] = (
    {
        "code": "youtube_non_authorized_stats",
        "name": "YouTube non-authorized statistics (30 days)",
        "retention_days": 30,
        "applies_to": "statistics",
        "notes": (
            "YouTube Developer Policies: non-authorized (API-key) statistics must be "
            "deleted or refreshed within 30 calendar days unless a later analytics "
            "storage amendment is approved."
        ),
    },
    {
        "code": "youtube_non_authorized_metadata",
        "name": "YouTube non-authorized metadata (30 days)",
        "retention_days": 30,
        "applies_to": "metadata",
        "notes": (
            "YouTube Developer Policies: titles, descriptions, comments, and similar "
            "non-statistical API data follow the 30-day refresh or delete rule."
        ),
    },
)
