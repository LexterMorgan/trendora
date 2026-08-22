"""Analytics-layer errors. Read path only; never raised by connectors."""


class AnalyticsError(Exception):
    """Base error for the analytics read layer."""


class AnalyticsQueryError(AnalyticsError):
    """Invalid query parameters (filters, timestamps, subject identity)."""


class AnalyticsAggregationError(AnalyticsError):
    """Unsupported or under-specified aggregation."""
