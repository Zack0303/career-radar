"""Deterministic Stage-1 rule filter and Markdown job-card renderer."""

from __future__ import annotations

import re
from typing import Optional

from career_radar.models import (
    FilterConfig,
    JobChangeType,
    JobPosting,
    RecruiterBrief,
    RuleMatchResult,
)


def _keyword_matches(keyword: str, text: str) -> bool:
    """Match pure-ASCII keywords on token boundaries to avoid substring false positives."""
    if not keyword:
        return False
    if all(ord(ch) < 128 for ch in keyword):
        pattern = r"(?<![A-Za-z0-9_])" + re.escape(keyword) + r"(?![A-Za-z0-9_])"
        return re.search(pattern, text, re.IGNORECASE) is not None
    return keyword.lower() in text.lower()


def evaluate_job(posting: JobPosting, config: FilterConfig) -> RuleMatchResult:
    """Evaluate a job posting against location, include, and exclude rules."""
    searchable = f"{posting.title}\n{posting.department}\n{posting.description}"
    location_lower = posting.location.lower()

    excluded_hits = tuple(kw for kw in config.exclude_keywords if _keyword_matches(kw, searchable))
    excluded_reasons = tuple(f"Excluded keyword matched: '{kw}'" for kw in excluded_hits)

    matched_locations: tuple[str, ...] = ()
    location_ok = True
    matched_reasons: list[str] = []

    if config.locations:
        matched_locations = tuple(loc for loc in config.locations if loc.lower() in location_lower)
        location_ok = bool(matched_locations)
        if matched_locations:
            matched_reasons.append(f"Location matched: {', '.join(matched_locations)}")
        else:
            excluded_reasons = excluded_reasons + (
                f"Location '{posting.location}' outside configured targets",
            )

    matched_keywords: tuple[str, ...] = ()
    include_ok = True
    if config.include_keywords:
        matched_keywords = tuple(kw for kw in config.include_keywords if _keyword_matches(kw, searchable))
        include_ok = bool(matched_keywords)
        if matched_keywords:
            matched_reasons.append(f"Keywords matched: {', '.join(matched_keywords)}")
        else:
            excluded_reasons = excluded_reasons + ("No configured include_keywords matched",)

    matched = (not excluded_hits) and location_ok and include_ok
    if not matched:
        score = 0
    else:
        title_bonus = sum(10 for kw in matched_keywords if _keyword_matches(kw, posting.title))
        base = len(matched_keywords) * 20 if matched_keywords else 50
        score = min(100, base + title_bonus)

    return RuleMatchResult(
        matched=matched,
        score=score,
        matched_locations=matched_locations,
        matched_keywords=matched_keywords,
        excluded_keywords=excluded_hits,
        matched_reasons=tuple(matched_reasons),
        excluded_reasons=excluded_reasons,
    )


def build_recruiter_brief(posting: JobPosting, match_result: RuleMatchResult) -> RecruiterBrief:
    """Build a conservative 5-line Recruiter Brief skeleton without fabricating evidence."""
    kw_summary = ", ".join(match_result.matched_keywords) if match_result.matched_keywords else "Rule filter passed"
    return RecruiterBrief(
        role=posting.title,
        company=posting.company,
        fit_summary=f"Stage-1 score {match_result.score}/100 ({kw_summary})",
        evidence_points=(
            "[Pending M2] Attach verified Project-Library IDs (e.g., P1, P3) from local workspace",
        ),
        location_availability=f"Target role location: {posting.location or 'Unspecified'} (confirm availability)",
        open_gaps="[Pending M2] Explicitly list unverified requirements rather than claiming coverage",
    )


def render_job_card_markdown(
    posting: JobPosting,
    match_result: RuleMatchResult,
    change_type: Optional[JobChangeType] = None,
) -> str:
    """Render a clean Markdown job evaluation card with a 5-line Recruiter Brief."""
    status_label = change_type.value.upper() if change_type is not None else "ACTIVE"
    reasons = "\n".join(f"- {reason}" for reason in match_result.matched_reasons) or "- Passed default filter"
    brief_lines = "\n".join(build_recruiter_brief(posting, match_result).to_lines())
    description_text = posting.description.strip() or "(No description provided)"

    return (
        f"# {posting.company} | {posting.title}\n\n"
        f"- **External ID**: `{posting.external_id}`\n"
        f"- **ATS Provider**: `{posting.provider.value}`\n"
        f"- **Diff Status**: `{status_label}`\n"
        f"- **Location**: {posting.location or 'Unspecified'}\n"
        f"- **Department**: {posting.department or 'Unspecified'}\n"
        f"- **Official URL**: {posting.url or 'N/A'}\n"
        f"- **Stage-1 Rule Score**: {match_result.score}/100\n\n"
        f"## Stage-1 Filter Signals\n\n"
        f"{reasons}\n\n"
        f"## Role Summary (From Source)\n\n"
        f"{description_text}\n\n"
        f"## Grounded Evidence & Gaps (M2 Workspace Slot)\n\n"
        f"- **Matched Evidence (`[Verified]` / `[Self-reported]`)**: `[Pending M2 grounded matcher]`\n"
        f"- **Declared Gaps (`[Gap]`)**: `[Pending M2 gap extraction]`\n"
        f"- **Questions to Verify Before Applying**: `[Confirm team scope, tech stack, and location policy]`\n\n"
        f"## Recruiter Brief (5-Line Shareable Summary)\n\n"
        f"{brief_lines}\n"
    )
