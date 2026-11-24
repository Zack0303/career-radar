"""ATS adapter exports and provider factory."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from career_radar.adapters.base import ATSAdapter, FixtureAdapter, TransportFn
from career_radar.adapters.greenhouse import GreenhouseAdapter
from career_radar.adapters.http import ATSRequestError
from career_radar.adapters.lever import LeverAdapter
from career_radar.adapters.smartrecruiters import SmartRecruitersAdapter
from career_radar.adapters.workday import WorkdayAdapter
from career_radar.models import ATSProvider


def get_adapter(
    provider: ATSProvider,
    *,
    max_pages: int = 5,
    timeout: float = 15.0,
    delay_sec: float = 0.25,
    transport: Optional[TransportFn] = None,
    fixture_path: Optional[Path] = None,
) -> ATSAdapter:
    """Instantiate the adapter corresponding to an ATSProvider."""
    if provider == ATSProvider.FIXTURE:
        if fixture_path is None:
            raise ValueError("fixture_path is required when provider is FIXTURE.")
        return FixtureAdapter(fixture_path)

    adapter_map = {
        ATSProvider.SMARTRECRUITERS: SmartRecruitersAdapter,
        ATSProvider.GREENHOUSE: GreenhouseAdapter,
        ATSProvider.LEVER: LeverAdapter,
        ATSProvider.WORKDAY: WorkdayAdapter,
    }
    adapter_cls = adapter_map.get(provider)
    if adapter_cls is None:
        raise ValueError(f"Unsupported ATS provider: {provider}")
    return adapter_cls(
        transport=transport,
        timeout=timeout,
        delay_sec=delay_sec,
        max_pages=max_pages,
    )


__all__ = [
    "ATSAdapter",
    "ATSRequestError",
    "FixtureAdapter",
    "GreenhouseAdapter",
    "LeverAdapter",
    "SmartRecruitersAdapter",
    "WorkdayAdapter",
    "get_adapter",
]
