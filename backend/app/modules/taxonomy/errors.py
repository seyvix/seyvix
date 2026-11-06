from __future__ import annotations


class TaxonomyNotFoundError(Exception):
    pass


class TaxonomyConflictError(Exception):
    pass


class TaxonomyValidationError(Exception):
    pass


class TaxonomyPermissionError(Exception):
    pass


class TaxonomyAIDisabledError(Exception):
    """An AI-only operation was requested while AI/taxonomy AI is disabled."""
