"""In-memory diagnostics over M5 MetricSeries. Not a forecasting model."""

from trendora.diagnostics.exceptions import DiagnosticsError, DiagnosticsValidationError
from trendora.diagnostics.models import CadenceClass, MonotonicityClass, SeriesDiagnostics
from trendora.diagnostics.service import DiagnosticsService, diagnose_series

__all__ = [
    "CadenceClass",
    "DiagnosticsError",
    "DiagnosticsService",
    "DiagnosticsValidationError",
    "MonotonicityClass",
    "SeriesDiagnostics",
    "diagnose_series",
]
