"""Lever ATS adapter using the public postings API."""

from __future__ import annotations

from typing import Any, Mapping

from career_radar.adapters.base import _BaseHTTPAdapter, _require_slug
from career_radar.adapters.http import strip_html
from career_radar.models import ATSProvider, JobPosting, TargetCompany


class LeverAdapter(_BaseHTTPAdapter):
    """Fetcher and normalizer for Lever public postings JSON."""

    provider = ATSProvider.LEVER

    def build_endpoint(self, target: TargetCompany) -> str:
        """Build the public Lever postings URL in JSON mode."""
        slug = _require_slug(target, self.provider)
        return f"https://api.lever.co/v0/postings/{slug}?mode=json"

    def fetch_jobs(self, target: TargetCompany) -> list[JobPosting]:
        """Fetch active postings from a Lever public board."""
        url = self.build_endpoint(target)
        items: Any = self._request_json("GET", url)
        if not isinstance(items, list):
            raise ValueError(f"Unexpected Lever response shape for '{target.name}'.")

        postings: list[JobPosting] = []
        for item in items:
            if not isinstance(item, Mapping):
                continue
            job_id = str(item.get("id") or "").strip()
            title = str(item.get("text") or "").strip()
            if not job_id or not title:
                continue

            cats = item.get("categories")
            location = ""
            department = ""
            if isinstance(cats, Mapping):
                location = str(cats.get("location") or "").strip()
                if not location and isinstance(cats.get("allLocations"), list):
                    location = "; ".join(str(x).strip() for x in cats["allLocations"] if str(x).strip())
                department = str(cats.get("department") or cats.get("team") or "").strip()

            description = str(item.get("descriptionPlain") or "").strip()
            if not description:
                description = strip_html(str(item.get("description") or ""))

            postings.append(
                JobPosting(
                    company=target.name,
                    provider=self.provider,
                    external_id=job_id,
                    title=title,
                    location=location,
                    department=department,
                    url=str(item.get("hostedUrl") or "").strip(),
                    description=description,
                    raw_payload=dict(item),
                )
            )
        return postings
