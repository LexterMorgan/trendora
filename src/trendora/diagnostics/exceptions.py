"""Diagnostic-layer errors. Read path only; never raised by connectors."""


class DiagnosticsError(Exception):
    """Base error for series diagnostics."""


class DiagnosticsValidationError(DiagnosticsError):
    """Invalid diagnostic input (timestamps, identity)."""
