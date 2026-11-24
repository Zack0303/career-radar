"""Workday ATS adapter using the Candidate Experience Site (CXS) JSON API."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping
from urllib.parse import urlparse

from career_radar.adapters.base import _BaseHTTPAdapter
from career_radar.adapters.http import strip_html
from career_radar.models import ATSProvider, FetchBatch, JobPosting, TargetCompany

# Workday CXS strictly rejects limit > 20 with HTTP 400 Bad Request.
_WORKDAY_PAGE_LIMIT = 20


class WorkdayAdapter(_BaseHTTPAdapter):
    """Paginated fetcher and normalizer for Workday CXS job listings."""

    provider = ATSProvider.WORKDAY

    def build_endpoint(self, target: TargetCompany) -> str:
        """Derive a Workday CXS jobs endpoint from a company career board URL."""
        raw_url = target.url.strip()
        if not raw_url:
            raise ValueError(f"Workday target '{target.name}' requires a career board URL.")
        parsed = urlparse(raw_url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"Invalid Workday URL for '{target.name}': {raw_url}")
        segments = [seg for seg in parsed.path.split("/") if seg]
        if not segments:
            raise ValueError(
                f"Workday URL for '{target.name}' must include a site path segment: {raw_url}"
            )
        tenant = parsed.netloc.split(".")[0]
        site = segments[-1]
        return f"{parsed.scheme}://{parsed.netloc}/wday/cxs/{tenant}/{site}/jobs"

    def fetch_jobs(self, target: TargetCompany) -> list[JobPosting]:
        """Fetch paginated postings from Workday CXS while respecting limit=20."""
        return list(self.fetch_batch(target).postings)

    def fetch_batch(self, target: TargetCompany) -> FetchBatch:
        """Fetch paginated Workday postings with completeness status."""
        endpoint = self.build_endpoint(target)
        base_board_url = target.url.strip().rstrip("/")
        postings: list[JobPosting] = []
        offset = 0
        known_total = 0
        is_complete = False

        for page_idx in range(self.max_pages):
            self._polite_sleep(page_idx)
            payload = {
                "appliedFacets": {},
                "limit": _WORKDAY_PAGE_LIMIT,
                "offset": offset,
                "searchText": target.search_text.strip(),
            }
            data: Any = self._request_json("POST", endpoint, payload=payload)
            if not isinstance(data, Mapping):
                raise ValueError(f"Unexpected Workday response shape for '{target.name}'.")

            if page_idx == 0:
                known_total = int(data.get("total") or 0)

            items = data.get("jobPostings") or []
            if not items:
                is_complete = True
                break

            for item in items:
                if not isinstance(item, Mapping):
                    continue
                title = str(item.get("title") or "").strip()
                external_path = str(item.get("externalPath") or "").strip()
                bullets = [
                    str(b).strip()
                    for b in (item.get("bulletFields") or ())
                    if str(b).strip()
                ]
                external_id = bullets[0] if bullets else external_path
                if not title or not external_id:
                    continue

                if external_path and not external_path.startswith("/"):
                    external_path = "/" + external_path
                public_url = f"{base_board_url}{external_path}" if external_path else base_board_url

                postings.append(
                    JobPosting(
                        company=target.name,
                        provider=self.provider,
                        external_id=external_id,
                        title=title,
                        location=str(item.get("locationsText") or "").strip(),
                        department="",
                        url=public_url,
                        description=" | ".join(bullets),
                        raw_payload=dict(item),
                    )
                )

            offset += len(items)
            if (known_total > 0 and offset >= known_total) or len(items) < _WORKDAY_PAGE_LIMIT:
                is_complete = True
                break

        return FetchBatch(postings=tuple(postings), is_complete=is_complete)

    def fetch_job_detail(self, target: TargetCompany, posting: JobPosting) -> JobPosting:
        """Fetch full JD description from Workday CXS posting detail endpoint."""
        ext_path = str(posting.raw_payload.get("externalPath") or "").strip()
        if not ext_path:
            return posting
        if not ext_path.startswith("/"):
            ext_path = "/" + ext_path
        jobs_endpoint = self.build_endpoint(target)
        detail_url = jobs_endpoint[: -len("/jobs")] + ext_path
        data = self._request_json("GET", detail_url)
        if not isinstance(data, Mapping):
            return posting

        info = data.get("jobPostingInfo")
        if not isinstance(info, Mapping):
            return posting
        cleaned = strip_html(str(info.get("jobDescription") or ""))
        if not cleaned:
            return posting
        return replace(posting, description=cleaned)
