"""Matcher package exports."""

from __future__ import annotations

from career_radar.matcher.evidence_validator import (
    ValidationIssue,
    ValidationResult,
    extract_numeric_claims,
    parse_evidence_ids,
    render_grounded_job_card,
    validate_match_payload,
)
from career_radar.matcher.rule_matcher import (
    build_recruiter_brief,
    evaluate_job,
    render_job_card_markdown,
)

__all__ = [
    "ValidationIssue",
    "ValidationResult",
    "build_recruiter_brief",
    "evaluate_job",
    "extract_numeric_claims",
    "parse_evidence_ids",
    "render_grounded_job_card",
    "render_job_card_markdown",
    "validate_match_payload",
]
