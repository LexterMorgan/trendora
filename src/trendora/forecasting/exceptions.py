"""Forecasting-layer errors. Read path only; never raised by connectors."""


class ForecastingError(Exception):
    """Base error for in-memory forecasting."""


class ForecastingValidationError(ForecastingError):
    """Invalid request parameters (horizon, interval, window, alpha, identity)."""


class InsufficientHistoryError(ForecastingError):
    """Not enough observations to fit the requested model."""
