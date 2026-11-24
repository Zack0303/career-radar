"""Deterministic anti-hallucination evidence validator and grounded job-card renderer."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from career_radar.models import RecruiterBrief

_ALLOWED_FIT_LEVELS = frozenset({"high", "medium", "low"})
_ALLOWED_EVIDENCE_LEVELS = frozenset({"verified", "self_reported"})

_TABLE_ID_RE = re.compile(r"^\|\s*(?:\*\*)?([A-Za-z]+\d+)(?:\*\*)?\s*\|", re.MULTILINE)
_HEADING_ID_RE = re.compile(
    r"^#{2,4}\s+(?:\*\*)?([A-Za-z]+\d+)(?:\*\*)?(?:[\s.:：]|$)",
    re.MULTILINE,
)

# Match numeric claims carrying units, percentages, multipliers, currency, or '+' bounds.
_NUMERIC_CLAIM_RE = re.compile(
    r"(?<!\w)(?:[$€£¥]\s*\d+(?:[.,]\d+)?[kKmMbB]?|\d+(?:[.,]\d+)?\s*(?:%|x|X|ms|s|sec|min|h|hr|hrs|k|K|m|M|B|GB|MB|TB|\+))(?![A-Za-z0-9_])"
)
_YEAR_RE = re.compile(r"^(?:19\d{2}|20[0-3]\d)$")


@dataclass(frozen=True)
class ValidationIssue:
    """Single deterministic validation error found in a match payload."""

    code: str
    message: str
    field: str


@dataclass(frozen=True)
class ValidationResult:
    """Result of validating an LLM-generated match payload against source evidence."""

    valid: bool
    issues: tuple[ValidationIssue, ...]


def parse_evidence_ids(markdown_text: str) -> set[str]:
    """Extract explicit project/experience IDs (e.g., P1, P10, E2) from Markdown."""
    ids = set(_TABLE_ID_RE.findall(markdown_text))
    ids.update(_HEADING_ID_RE.findall(markdown_text))
    return {item.strip() for item in ids if item.strip()}


def extract_numeric_claims(text: str) -> set[str]:
    """Extract metric-bearing numeric tokens while ignoring plain years."""
    found: set[str] = set()
    for match in _NUMERIC_CLAIM_RE.finditer(text):
        token = match.group(0).strip()
        if _YEAR_RE.match(token):
            continue
        found.add(token)
    return found


def _validate_brief(
    brief_raw: Any,
    source_lower: str,
    issues: list[ValidationIssue],
) -> None:
    if not isinstance(brief_raw, Mapping):
        issues.append(
            ValidationIssue(
                code="INVALID_RECRUITER_BRIEF",
                message="recruiter_brief must be an object.",
                field="recruiter_brief",
            )
        )
        return

    req_brief = ("role", "company", "fit_summary", "evidence_points", "location_availability", "open_gaps")
    for key in req_brief:
        val = brief_raw.get(key)
        if key == "evidence_points":
            if not isinstance(val, list) or not [str(x).strip() for x in val if str(x).strip()]:
                issues.append(
                    ValidationIssue(
                        code="INVALID_RECRUITER_BRIEF",
                        message="recruiter_brief.evidence_points must be a non-empty list.",
                        field="recruiter_brief.evidence_points",
                    )
                )
        elif not str(val or "").strip():
            issues.append(
                ValidationIssue(
                    code="INVALID_RECRUITER_BRIEF",
                    message=f"recruiter_brief.{key} must be non-empty.",
                    field=f"recruiter_brief.{key}",
                )
            )

    if any(issue.field.startswith("recruiter_brief") for issue in issues):
        return

    for idx, point in enumerate(brief_raw["evidence_points"]):
        point_text = str(point)
        for token in extract_numeric_claims(point_text):
            if token.lower() not in source_lower:
                issues.append(
                    ValidationIssue(
                        code="UNGROUNDED_NUMERIC_CLAIM",
                        message=f"Numeric claim '{token}' in recruiter_brief.evidence_points[{idx}] was not found in source corpus.",
                        field=f"recruiter_brief.evidence_points[{idx}]",
                    )
                )

    brief = RecruiterBrief(
        role=str(brief_raw["role"]).strip(),
        company=str(brief_raw["company"]).strip(),
        fit_summary=str(brief_raw["fit_summary"]).strip(),
        evidence_points=tuple(str(x).strip() for x in brief_raw["evidence_points"] if str(x).strip()),
        location_availability=str(brief_raw["location_availability"]).strip(),
        open_gaps=str(brief_raw["open_gaps"]).strip(),
    )
    lines = brief.to_lines()
    if len(lines) != 5 or any(not line.strip() for line in lines):
        issues.append(
            ValidationIssue(
                code="INVALID_RECRUITER_BRIEF",
                message="recruiter_brief must render exactly 5 non-empty lines.",
                field="recruiter_brief",
            )
        )


def validate_match_payload(
    payload: Mapping[str, Any],
    valid_evidence_ids: set[str],
    source_corpus: str,
) -> ValidationResult:
    """Validate structured job match output against declared evidence IDs and source metrics."""
    issues: list[ValidationIssue] = []
    source_lower = source_corpus.lower()

    for key in ("company", "external_id", "title"):
        if not str(payload.get(key) or "").strip():
            issues.append(
                ValidationIssue(
                    code="MISSING_REQUIRED_FIELD",
                    message=f"Required string field '{key}' is missing or empty.",
                    field=key,
                )
            )

    fit_level = str(payload.get("fit_level") or "").strip().lower()
    if fit_level not in _ALLOWED_FIT_LEVELS:
        issues.append(
            ValidationIssue(
                code="INVALID_FIT_LEVEL",
                message=f"fit_level must be one of {sorted(_ALLOWED_FIT_LEVELS)}.",
                field="fit_level",
            )
        )

    for list_key in ("matched_evidence", "gaps", "questions_to_ask"):
        if not isinstance(payload.get(list_key), list):
            issues.append(
                ValidationIssue(
                    code="MISSING_REQUIRED_FIELD",
                    message=f"Required list field '{list_key}' must be a list.",
                    field=list_key,
                )
            )

    matched_evidence = payload.get("matched_evidence")
    if isinstance(matched_evidence, list):
        for idx, item in enumerate(matched_evidence):
            prefix = f"matched_evidence[{idx}]"
            if not isinstance(item, Mapping):
                issues.append(
                    ValidationIssue(
                        code="INVALID_EVIDENCE_ITEM",
                        message="Each matched_evidence entry must be an object.",
                        field=prefix,
                    )
                )
                continue
            ev_id = str(item.get("evidence_id") or "").strip()
            if not ev_id or ev_id not in valid_evidence_ids:
                issues.append(
                    ValidationIssue(
                        code="UNKNOWN_EVIDENCE_ID",
                        message=f"Evidence ID '{ev_id}' does not exist in source files ({sorted(valid_evidence_ids)}).",
                        field=f"{prefix}.evidence_id",
                    )
                )
            level = str(item.get("level") or "").strip().lower()
            if level not in _ALLOWED_EVIDENCE_LEVELS:
                issues.append(
                    ValidationIssue(
                        code="INVALID_EVIDENCE_LEVEL",
                        message=f"Evidence level '{level}' must be 'verified' or 'self_reported'.",
                        field=f"{prefix}.level",
                    )
                )
            claim = str(item.get("claim") or "").strip()
            if not claim:
                issues.append(
                    ValidationIssue(
                        code="MISSING_REQUIRED_FIELD",
                        message="Evidence claim must not be empty.",
                        field=f"{prefix}.claim",
                    )
                )
                continue
            for token in extract_numeric_claims(claim):
                if token.lower() not in source_lower:
                    issues.append(
                        ValidationIssue(
                            code="UNGROUNDED_NUMERIC_CLAIM",
                            message=f"Numeric claim '{token}' in '{prefix}.claim' was not found in source corpus.",
                            field=f"{prefix}.claim",
                        )
                    )

    _validate_brief(payload.get("recruiter_brief"), source_lower, issues)

    return ValidationResult(valid=not issues, issues=tuple(issues))


def render_grounded_job_card(
    match_payload: Mapping[str, Any],
    validation: ValidationResult,
) -> str:
    """Render a complete, evidence-grounded Markdown job evaluation card."""
    if not validation.valid:
        raise ValueError("Cannot render grounded job card for an invalid match payload.")

    company = str(match_payload["company"]).strip()
    title = str(match_payload["title"]).strip()
    external_id = str(match_payload["external_id"]).strip()
    fit_level = str(match_payload["fit_level"]).strip().upper()
    url = str(match_payload.get("url") or "N/A").strip()
    location = str(match_payload.get("location") or "Unspecified").strip()

    evidence_rows: list[str] = []
    for item in match_payload["matched_evidence"]:
        ev_id = str(item["evidence_id"]).strip()
        level = str(item["level"]).strip()
        claim = str(item["claim"]).strip().replace("|", "\\|")
        evidence_rows.append(f"| `{ev_id}` | `{level}` | {claim} |")
    evidence_table = (
        "\n".join(evidence_rows)
        if evidence_rows
        else "| - | - | No direct project evidence claimed; review gaps below. |"
    )

    gaps_md = "\n".join(f"- `[Gap]` {str(g).strip()}" for g in match_payload["gaps"] if str(g).strip())
    if not gaps_md:
        gaps_md = "- None identified"

    questions_md = "\n".join(
        f"- {str(q).strip()}" for q in match_payload["questions_to_ask"] if str(q).strip()
    )
    if not questions_md:
        questions_md = "- None"

    brief_raw = match_payload["recruiter_brief"]
    brief = RecruiterBrief(
        role=str(brief_raw["role"]).strip(),
        company=str(brief_raw["company"]).strip(),
        fit_summary=str(brief_raw["fit_summary"]).strip(),
        evidence_points=tuple(str(x).strip() for x in brief_raw["evidence_points"] if str(x).strip()),
        location_availability=str(brief_raw["location_availability"]).strip(),
        open_gaps=str(brief_raw["open_gaps"]).strip(),
    )
    brief_lines = "\n".join(brief.to_lines())

    return (
        f"# {company} | {title}\n\n"
        f"- **External ID**: `{external_id}`\n"
        f"- **Location**: {location}\n"
        f"- **Official URL**: {url}\n"
        f"- **Fit Level**: `{fit_level}`\n"
        f"- **Evidence Validation**: `PASSED`\n\n"
        f"## Grounded Evidence\n\n"
        f"| Evidence ID | Level | Grounded Claim |\n"
        f"| :--- | :--- | :--- |\n"
        f"{evidence_table}\n\n"
        f"## Declared Gaps\n\n"
        f"{gaps_md}\n\n"
        f"## Questions to Verify Before Applying\n\n"
        f"{questions_md}\n\n"
        f"## Recruiter Brief (5-Line Shareable Summary)\n\n"
        f"{brief_lines}\n"
    )
