from __future__ import annotations


class TagNotFoundError(Exception):
    pass


class TagConflictError(Exception):
    pass


class TagValidationError(Exception):
    pass


class TaggingDisabledError(Exception):
    """AI is not configured or automatic tagging is switched off (`AI_TAGS_ENABLED`)."""
