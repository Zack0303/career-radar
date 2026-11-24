"""Base ATS adapter protocol, HTTP base class, and offline fixture adapter."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Optional, Protocol

from career_radar.adapters.http import http_json_request
from career_radar.models import ATSProvider, FetchBatch, JobPosting, TargetCompany

TransportFn = Callable[
    [str, str, Optional[Mapping[str, Any]], Optional[Mapping[str, str]], float],
    Any,
]


class ATSAdapter(Protocol):
    """Protocol implemented by every official ATS and fixture adapter."""

    provider: ATSProvider

    def fetch_jobs(self, target: TargetCompany) -> list[JobPosting]:
        """Return normalized postings currently active for the target company."""
        ...


class _BaseHTTPAdapter:
    """Shared HTTP transport, timeout, pagination cap, and polite throttling."""

    provider: ATSProvider

    def __init__(
        self,
        *,
        transport: Optional[TransportFn] = None,
        timeout: float = 15.0,
        delay_sec: float = 0.25,
        max_pages: int = 5,
    ) -> None:
        self._transport: TransportFn = transport or http_json_request
        self.timeout = float(timeout)
        self.delay_sec = max(0.0, float(delay_sec))
        self.max_pages = max(1, int(max_pages))

    def build_endpoint(self, target: TargetCompany) -> str:
        """Construct the provider's public API endpoint for the given target."""
        raise NotImplementedError

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        payload: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> Any:
        return self._transport(method, url, payload, headers, self.timeout)

    def _polite_sleep(self, page_index: int) -> None:
        if page_index > 0 and self.delay_sec > 0:
            time.sleep(self.delay_sec)

    def fetch_job_detail(self, target: TargetCompany, posting: JobPosting) -> JobPosting:
        """Optionally enrich a posting with full description; defaults to a no-op."""
        return posting

    def fetch_batch(self, target: TargetCompany) -> FetchBatch:
        """Return postings along with completeness metadata (defaults to complete)."""
        return FetchBatch(postings=tuple(self.fetch_jobs(target)), is_complete=True)


def _require_slug(target: TargetCompany, provider: ATSProvider) -> str:
    """Extract a validated slug for slug-based ATS APIs."""
    slug = target.slug.strip()
    if not slug:
        raise ValueError(f"Target '{target.name}' requires a non-empty slug for {provider.value}.")
    return slug


class FixtureAdapter:
    """Reads synthetic or recorded job postings from a local JSON fixture file."""

    provider = ATSProvider.FIXTURE

    def __init__(self, fixture_path: Path) -> None:
        self.fixture_path = Path(fixture_path)

    def load_all(self) -> list[JobPosting]:
        """Load every posting from the fixture file."""
        raw_items: list[dict[str, Any]] = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        return [
            JobPosting(
                company=str(item["company"]),
                provider=ATSProvider(item.get("provider", ATSProvider.FIXTURE.value)),
                external_id=str(item["external_id"]),
                title=str(item["title"]),
                location=str(item.get("location", "")),
                department=str(item.get("department", "")),
                url=str(item.get("url", "")),
                description=str(item.get("description", "")),
                raw_payload=item,
            )
            for item in raw_items
        ]

    def fetch_jobs(self, target: TargetCompany) -> list[JobPosting]:
        """Return fixture postings filtered by company name (or all when name == '*')."""
        all_postings = self.load_all()
        if target.name.strip() == "*":
            return all_postings
        wanted = target.name.strip().lower()
        return [posting for posting in all_postings if posting.company.strip().lower() == wanted]
