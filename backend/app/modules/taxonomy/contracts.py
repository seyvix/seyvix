from __future__ import annotations

from enum import StrEnum


class TaxonomyAssignmentStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    OVERRIDDEN = "overridden"


class AutomaticApplyMode(StrEnum):
    DISABLED = "disabled"
    MANUAL_REVIEW_ONLY = "manual_review_only"
    AUTO_APPLY_HIGH_CONFIDENCE = "auto_apply_high_confidence"
