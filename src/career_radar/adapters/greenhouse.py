"""Greenhouse ATS adapter using the public job boards API."""

from __future__ import annotations

from typing import Any, Mapping

from career_radar.adapters.base import _BaseHTTPAdapter, _require_slug
from career_radar.adapters.http import strip_html
from career_radar.models import ATSProvider, JobPosting, TargetCompany


class GreenhouseAdapter(_BaseHTTPAdapter):
    """Fetcher and normalizer for Greenhouse public job board JSON."""

    provider = ATSProvider.GREENHOUSE

    def build_endpoint(self, target: TargetCompany) -> str:
        """Build the public Greenhouse jobs URL with full HTML content enabled."""
        slug = _require_slug(target, self.provider)
        return f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"

    def fetch_jobs(self, target: TargetCompany) -> list[JobPosting]:
        """Fetch active postings from a Greenhouse public board."""
        url = self.build_endpoint(target)
        data: Any = self._request_json("GET", url)
        if not isinstance(data, Mapping):
            raise ValueError(f"Unexpected Greenhouse response shape for '{target.name}'.")

        jobs = data.get("jobs") or []
        postings: list[JobPosting] = []
        for item in jobs:
            if not isinstance(item, Mapping):
                continue
            job_id = str(item.get("id") or "").strip()
            title = str(item.get("title") or "").strip()
            if not job_id or not title:
                continue

            loc_obj = item.get("location")
            location = str(loc_obj.get("name") or "").strip() if isinstance(loc_obj, Mapping) else ""

            dept_names = [
                str(dept.get("name") or "").strip()
                for dept in (item.get("departments") or ())
                if isinstance(dept, Mapping) and str(dept.get("name") or "").strip()
            ]
            description = strip_html(str(item.get("content") or ""))

            postings.append(
                JobPosting(
                    company=target.name,
                    provider=self.provider,
                    external_id=job_id,
                    title=title,
                    location=location,
                    department=", ".join(dept_names),
                    url=str(item.get("absolute_url") or "").strip(),
                    description=description,
                    raw_payload=dict(item),
                )
            )
        return postings
