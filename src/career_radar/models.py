"""Core domain models for Career Radar."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
from typing import Any, Mapping, Optional


class ATSProvider(str, Enum):
    """Supported official Applicant Tracking System providers."""

    SMARTRECRUITERS = "smartrecruiters"
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    WORKDAY = "workday"
    FIXTURE = "fixture"


class JobChangeType(str, Enum):
    """Incremental diff state for a job posting across scans."""

    NEW = "new"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    CLOSED = "closed"


class EvidenceLevel(str, Enum):
    """Evidence classification enforced across profiles and matching outputs."""

    VERIFIED = "verified"
    SELF_REPORTED = "self_reported"
    GAP = "gap"


def _normalize_for_hash(text: str) -> str:
    """Normalize line endings and surrounding whitespace for deterministic hashing."""
    return "\n".join(line.strip() for line in text.replace("\r\n", "\n").split("\n")).strip()


@dataclass(frozen=True)
class TargetCompany:
    """Configuration for a single company career board to monitor."""

    name: str
    ats: ATSProvider
    slug: str = ""
    url: str = ""
    enabled: bool = True
    search_text: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("TargetCompany.name must not be empty.")
        if isinstance(self.ats, str) and not isinstance(self.ats, ATSProvider):
            object.__setattr__(self, "ats", ATSProvider(self.ats))
        if not self.enabled or self.ats == ATSProvider.FIXTURE:
            return
        if self.ats == ATSProvider.WORKDAY and not self.url.strip():
            raise ValueError(f"Workday target '{self.name}' requires a non-empty url.")
        if self.ats != ATSProvider.WORKDAY and not (self.slug.strip() or self.url.strip()):
            raise ValueError(f"Target '{self.name}' ({self.ats.value}) requires a slug or url.")


@dataclass(frozen=True)
class FilterConfig:
    """Deterministic Stage-1 filtering rules."""

    locations: tuple[str, ...] = ()
    include_keywords: tuple[str, ...] = ()
    exclude_keywords: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> FilterConfig:
        """Build a FilterConfig from a JSON/YAML dictionary."""
        return cls(
            locations=tuple(str(item).strip() for item in data.get("locations", ()) if str(item).strip()),
            include_keywords=tuple(
                str(item).strip() for item in data.get("include_keywords", ()) if str(item).strip()
            ),
            exclude_keywords=tuple(
                str(item).strip() for item in data.get("exclude_keywords", ()) if str(item).strip()
            ),
        )


@dataclass(frozen=True)
class JobPosting:
    """Normalized job posting returned by any ATS adapter."""

    company: str
    provider: ATSProvider
    external_id: str
    title: str
    location: str
    department: str = ""
    url: str = ""
    description: str = ""
    raw_payload: Mapping[str, Any] = field(default_factory=dict)
    content_hash: str = ""

    def __post_init__(self) -> None:
        if not self.company.strip():
            raise ValueError("JobPosting.company must not be empty.")
        if not self.external_id.strip():
            raise ValueError("JobPosting.external_id must not be empty.")
        if not self.title.strip():
            raise ValueError("JobPosting.title must not be empty.")
        if isinstance(self.provider, str) and not isinstance(self.provider, ATSProvider):
            object.__setattr__(self, "provider", ATSProvider(self.provider))
        if not self.content_hash:
            object.__setattr__(self, "content_hash", self.compute_content_hash())

    def compute_content_hash(self) -> str:
        """Compute deterministic SHA-256 hash over normalized job fields."""
        canonical = "\n||\n".join(
            [
                _normalize_for_hash(self.title),
                _normalize_for_hash(self.location),
                _normalize_for_hash(self.department),
                _normalize_for_hash(self.url),
                _normalize_for_hash(self.description),
            ]
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class JobDiff:
    """Single job state transition emitted by a scan."""

    posting: JobPosting
    change_type: JobChangeType
    previous_hash: Optional[str] = None


@dataclass(frozen=True)
class ScanResult:
    """Summary of recording one company scan into the incremental store."""

    company_name: str
    provider: ATSProvider
    scan_run_id: int
    diffs: tuple[JobDiff, ...]
    new_count: int
    updated_count: int
    unchanged_count: int
    closed_count: int


@dataclass(frozen=True)
class ScanError:
    """Isolated failure record when scanning a single target company."""

    company_name: str
    provider: ATSProvider
    error_message: str


@dataclass(frozen=True)
class FetchBatch:
    """Adapter fetch result indicating whether pagination retrieved the complete list."""

    postings: tuple[JobPosting, ...]
    is_complete: bool = True


@dataclass(frozen=True)
class RuleMatchResult:
    """Transparent Stage-1 rule filter outcome for a job posting."""

    matched: bool
    score: int
    matched_locations: tuple[str, ...]
    matched_keywords: tuple[str, ...]
    excluded_keywords: tuple[str, ...]
    matched_reasons: tuple[str, ...]
    excluded_reasons: tuple[str, ...]


@dataclass(frozen=True)
class RecruiterBrief:
    """Concise 5-line brief for recruiter/hiring-manager alignment."""

    role: str
    company: str
    fit_summary: str
    evidence_points: tuple[str, ...]
    location_availability: str
    open_gaps: str

    def to_lines(self) -> list[str]:
        """Render the brief as exactly five bullet lines."""
        evidence = "; ".join(self.evidence_points) if self.evidence_points else "Pending M2 evidence mapping"
        return [
            f"- **Role**: {self.role} @ {self.company}",
            f"- **Stage-1 Signal**: {self.fit_summary}",
            f"- **Grounded Evidence**: {evidence}",
            f"- **Location / Availability**: {self.location_availability}",
            f"- **Declared Gaps / Boundary**: {self.open_gaps}",
        ]
