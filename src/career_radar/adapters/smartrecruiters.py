"""SmartRecruiters ATS adapter using the public postings API."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping
from urllib.parse import urlencode

from career_radar.adapters.base import _BaseHTTPAdapter, _require_slug
from career_radar.adapters.http import strip_html
from career_radar.models import ATSProvider, FetchBatch, JobPosting, TargetCompany

_SMARTRECRUITERS_PAGE_LIMIT = 100


def _format_location(loc: Any) -> str:
    if not isinstance(loc, Mapping):
        return ""
    parts = [str(loc.get(key) or "").strip() for key in ("city", "region", "country")]
    text = ", ".join(part for part in parts if part)
    if loc.get("remote"):
        return f"{text} (Remote)" if text else "Remote"
    return text


def _format_snippet(item: Mapping[str, Any]) -> str:
    snippets: list[str] = []
    for key in ("typeOfEmployment", "experienceLevel", "function", "industry"):
        val = item.get(key)
        if isinstance(val, Mapping) and val.get("label"):
            snippets.append(f"{key}: {val['label']}")
    custom_fields = item.get("customField") or []
    if isinstance(custom_fields, list):
        for cf in custom_fields:
            if isinstance(cf, Mapping) and cf.get("fieldLabel") and cf.get("valueLabel"):
                snippets.append(f"{cf['fieldLabel']}: {cf['valueLabel']}")
    return " | ".join(snippets)


class SmartRecruitersAdapter(_BaseHTTPAdapter):
    """Paginated fetcher and normalizer for SmartRecruiters public postings."""

    provider = ATSProvider.SMARTRECRUITERS

    def build_endpoint(self, target: TargetCompany) -> str:
        """Build the public SmartRecruiters postings URL for a company slug."""
        slug = _require_slug(target, self.provider)
        return f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"

    def fetch_jobs(self, target: TargetCompany) -> list[JobPosting]:
        """Fetch paginated active postings from SmartRecruiters."""
        return list(self.fetch_batch(target).postings)

    def fetch_batch(self, target: TargetCompany) -> FetchBatch:
        """Fetch paginated SmartRecruiters postings with completeness status."""
        slug = _require_slug(target, self.provider)
        base_url = self.build_endpoint(target)
        postings: list[JobPosting] = []
        offset = 0
        is_complete = False

        for page_idx in range(self.max_pages):
            self._polite_sleep(page_idx)
            params: dict[str, Any] = {
                "offset": offset,
                "limit": _SMARTRECRUITERS_PAGE_LIMIT,
            }
            if target.search_text.strip():
                params["q"] = target.search_text.strip()

            data = self._request_json("GET", f"{base_url}?{urlencode(params)}")
            if not isinstance(data, Mapping):
                raise ValueError(f"Unexpected SmartRecruiters response shape for '{target.name}'.")

            content = data.get("content") or []
            if not content:
                is_complete = True
                break

            for item in content:
                if not isinstance(item, Mapping):
                    continue
                job_id = str(item.get("id") or "").strip()
                title = str(item.get("name") or "").strip()
                if not job_id or not title:
                    continue
                dept_obj = item.get("department")
                department = (
                    str(dept_obj.get("label") or "").strip()
                    if isinstance(dept_obj, Mapping)
                    else ""
                )
                public_url = f"https://jobs.smartrecruiters.com/{slug}/{job_id}"
                if not slug:
                    public_url = str(item.get("ref") or "").strip()

                postings.append(
                    JobPosting(
                        company=target.name,
                        provider=self.provider,
                        external_id=job_id,
                        title=title,
                        location=_format_location(item.get("location")),
                        department=department,
                        url=public_url,
                        description=_format_snippet(item),
                        raw_payload=dict(item),
                    )
                )

            offset += len(content)
            total_found = int(data.get("totalFound") or 0)
            if (total_found > 0 and offset >= total_found) or len(content) < _SMARTRECRUITERS_PAGE_LIMIT:
                is_complete = True
                break

        return FetchBatch(postings=tuple(postings), is_complete=is_complete)

    def fetch_job_detail(self, target: TargetCompany, posting: JobPosting) -> JobPosting:
        """Fetch full JD sections for a matched SmartRecruiters posting without altering content_hash."""
        slug = _require_slug(target, self.provider)
        detail_url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{posting.external_id}"
        data = self._request_json("GET", detail_url)
        if not isinstance(data, Mapping):
            return posting

        job_ad = data.get("jobAd")
        sections = job_ad.get("sections") if isinstance(job_ad, Mapping) else None
        if not isinstance(sections, Mapping):
            return posting

        ordered_keys = (
            ("jobDescription", "Job Description"),
            ("qualifications", "Qualifications"),
            ("additionalInformation", "Additional Information"),
            ("companyDescription", "Company Description"),
        )
        parts: list[str] = []
        for key, heading in ordered_keys:
            sec = sections.get(key)
            if isinstance(sec, Mapping) and sec.get("text"):
                cleaned = strip_html(str(sec["text"]))
                if cleaned:
                    parts.append(f"### {heading}\n{cleaned}")
        if not parts:
            return posting
        return replace(posting, description="\n\n".join(parts))
