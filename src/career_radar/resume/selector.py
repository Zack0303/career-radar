"""Deterministic JD-based project selector (zero text mutation)."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

_ASCII_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+#.-]{1,}")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")

_STOP_WORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "for", "with", "without", "to", "of", "in", "on",
        "at", "by", "from", "into", "is", "are", "be", "will", "can", "you", "your",
        "our", "we", "they", "their", "this", "that", "as", "not", "but", "all",
        "role", "team", "work", "working", "experience", "build", "using", "china",
    }
)


def _extract_jd_terms(jd_text: str) -> tuple[set[str], set[str]]:
    """Extract ASCII technical tokens and CJK bigrams from a job description."""
    ascii_terms: set[str] = set()
    for match in _ASCII_TOKEN_RE.finditer(jd_text):
        token = match.group(0).strip(".-").lower()
        if len(token) >= 2 and token not in _STOP_WORDS:
            ascii_terms.add(token)

    cjk_terms: set[str] = set()
    for run in _CJK_RUN_RE.findall(jd_text):
        if len(run) <= 4:
            cjk_terms.add(run)
        for idx in range(len(run) - 1):
            cjk_terms.add(run[idx : idx + 2])
    return ascii_terms, cjk_terms


def select_projects_for_job(
    projects: Sequence[Mapping[str, Any]],
    jd_text: str,
    max_projects: int = 4,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Rank and select top projects matching jd_text without mutating project content."""
    if max_projects < 1:
        raise ValueError("max_projects must be at least 1.")

    ascii_terms, cjk_terms = _extract_jd_terms(jd_text)
    scored: list[tuple[int, int, dict[str, Any], list[str]]] = []

    for idx, proj in enumerate(projects):
        title_ctx = f"{proj.get('name', '')} {proj.get('context', '')}"
        body = " ".join(
            [str(proj.get("intro", ""))] + [str(b) for b in proj.get("bullets", ())]
        )
        title_ascii = {t.strip(".-").lower() for t in _ASCII_TOKEN_RE.findall(title_ctx)}
        body_ascii = {t.strip(".-").lower() for t in _ASCII_TOKEN_RE.findall(body)}

        title_lower = title_ctx.lower()
        body_lower = body.lower()

        matched_terms: list[str] = []
        score = 0

        for term in sorted(ascii_terms):
            if term in title_ascii:
                score += 3
                matched_terms.append(term)
            elif term in body_ascii:
                score += 1
                matched_terms.append(term)

        for term in sorted(cjk_terms):
            if term in title_lower:
                score += 3
                matched_terms.append(term)
            elif term in body_lower:
                score += 1
                matched_terms.append(term)

        scored.append((score, idx, dict(proj), matched_terms))

    ranked = sorted(scored, key=lambda item: (-item[0], item[1]))
    selected_indices = {item[1] for item in ranked[:max_projects]}
    selected_projects = [item[2] for item in ranked[:max_projects]]

    report = [
        {
            "name": str(item[2].get("name", "")),
            "score": item[0],
            "matched_terms": item[3][:12],
            "selected": item[1] in selected_indices,
        }
        for item in ranked
    ]
    return selected_projects, report
