"""Unit tests for official ATS adapters, HTML sanitization, and scan error isolation."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from typing import Any, Mapping, Optional

from career_radar.adapters import (
    ATSRequestError,
    GreenhouseAdapter,
    LeverAdapter,
    SmartRecruitersAdapter,
    WorkdayAdapter,
)
from career_radar.adapters.http import strip_html
from career_radar.cli import cmd_scan, cmd_status
from career_radar.models import ATSProvider, TargetCompany


class FakeTransport:
    """Deterministic fake HTTP JSON transport recording every request."""

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        method: str,
        url: str,
        payload: Optional[Mapping[str, Any]],
        headers: Optional[Mapping[str, str]],
        timeout: float,
    ) -> Any:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "payload": dict(payload) if payload is not None else None,
                "headers": dict(headers) if headers is not None else None,
                "timeout": timeout,
            }
        )
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


class HTMLSanitizerTests(unittest.TestCase):
    def test_strip_html_handles_double_escaped_greenhouse_markup(self) -> None:
        raw = "&lt;p&gt;Build &amp;amp; verify RAG &lt;b&gt;pipelines&lt;/b&gt;.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Python&lt;/li&gt;&lt;/ul&gt;"
        cleaned = strip_html(raw)
        self.assertIn("Build & verify RAG pipelines.", cleaned)
        self.assertIn("- Python", cleaned)
        self.assertNotIn("<p>", cleaned)
        self.assertNotIn("&lt;", cleaned)


class LiveAdaptersTests(unittest.TestCase):
    def test_smartrecruiters_pagination_and_normalization(self) -> None:
        page0_items = [
            {
                "id": f"SR-{idx}",
                "name": f"AI Engineer {idx}",
                "location": {"city": "Suzhou", "region": "JS", "country": "cn", "remote": False},
                "department": {"label": "Engineering"},
                "typeOfEmployment": {"label": "Full-time"},
            }
            for idx in range(100)
        ]
        page1_items = [
            {
                "id": "SR-100",
                "name": "Remote Data Engineer",
                "location": {"city": "Shanghai", "country": "cn", "remote": True},
                "department": {"label": "Data"},
            }
        ]
        transport = FakeTransport(
            [
                {"limit": 100, "offset": 0, "totalFound": 101, "content": page0_items},
                {"limit": 100, "offset": 100, "totalFound": 101, "content": page1_items},
            ]
        )
        adapter = SmartRecruitersAdapter(transport=transport, delay_sec=0.0, max_pages=5)
        target = TargetCompany(name="Nova", ats=ATSProvider.SMARTRECRUITERS, slug="NovaSlug")

        jobs = adapter.fetch_jobs(target)
        self.assertEqual(len(jobs), 101)
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(jobs[0].url, "https://jobs.smartrecruiters.com/NovaSlug/SR-0")
        self.assertEqual(jobs[-1].location, "Shanghai, cn (Remote)")
        self.assertEqual(jobs[-1].department, "Data")

    def test_greenhouse_normalization_and_html_unescape(self) -> None:
        transport = FakeTransport(
            [
                {
                    "jobs": [
                        {
                            "id": 9981,
                            "title": "Applied AI Engineer",
                            "location": {"name": "Remote"},
                            "absolute_url": "https://boards.greenhouse.io/helios/jobs/9981",
                            "departments": [{"id": 1, "name": "Applied AI"}],
                            "content": "&lt;p&gt;Evaluate LLM tool calls.&lt;/p&gt;",
                        }
                    ]
                }
            ]
        )
        adapter = GreenhouseAdapter(transport=transport, delay_sec=0.0)
        jobs = adapter.fetch_jobs(TargetCompany(name="Helios", ats=ATSProvider.GREENHOUSE, slug="helios"))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].external_id, "9981")
        self.assertEqual(jobs[0].department, "Applied AI")
        self.assertEqual(jobs[0].description, "Evaluate LLM tool calls.")

    def test_lever_normalization(self) -> None:
        transport = FakeTransport(
            [
                [
                    {
                        "id": "uuid-abc",
                        "text": "Platform Data Engineer",
                        "hostedUrl": "https://jobs.lever.co/meridian/uuid-abc",
                        "categories": {
                            "location": "Shanghai",
                            "team": "Data Infra",
                        },
                        "descriptionPlain": "Own dbt and PostgreSQL pipelines.",
                    }
                ]
            ]
        )
        adapter = LeverAdapter(transport=transport, delay_sec=0.0)
        jobs = adapter.fetch_jobs(TargetCompany(name="Meridian", ats=ATSProvider.LEVER, slug="meridian"))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].title, "Platform Data Engineer")
        self.assertEqual(jobs[0].department, "Data Infra")
        self.assertIn("PostgreSQL", jobs[0].description)

    def test_workday_enforces_limit_20_and_retains_page0_total(self) -> None:
        page0_postings = [
            {
                "title": f"LLM Engineer {idx}",
                "locationsText": "Shanghai, China",
                "externalPath": f"/job/Shanghai/LLM-Engineer_{idx}",
                "bulletFields": [f"REQ-{idx}", "Full time"],
            }
            for idx in range(20)
        ]
        page1_postings = [
            {
                "title": "Data Architect",
                "locationsText": "Suzhou, China",
                "externalPath": "/job/Suzhou/Data-Architect_20",
                "bulletFields": ["REQ-20", "Full time"],
            }
        ]
        transport = FakeTransport(
            [
                {"total": 21, "jobPostings": page0_postings},
                # Workday frequently returns total=0 on subsequent pages.
                {"total": 0, "jobPostings": page1_postings},
            ]
        )
        adapter = WorkdayAdapter(transport=transport, delay_sec=0.0, max_pages=5)
        target = TargetCompany(
            name="Apex",
            ats=ATSProvider.WORKDAY,
            url="https://apex.wd3.myworkdayjobs.com/en-US/Careers",
            search_text="AI",
        )

        jobs = adapter.fetch_jobs(target)
        self.assertEqual(len(jobs), 21)
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(transport.calls[0]["payload"]["limit"], 20)
        self.assertEqual(transport.calls[1]["payload"]["offset"], 20)
        self.assertEqual(jobs[-1].external_id, "REQ-20")
        self.assertEqual(
            jobs[-1].url,
            "https://apex.wd3.myworkdayjobs.com/en-US/Careers/job/Suzhou/Data-Architect_20",
        )


class ScanCommandErrorIsolationTests(unittest.TestCase):
    def test_scan_isolates_failing_company_and_writes_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            config_path = tmp_path / "targets.json"
            db_path = tmp_path / "career_radar.db"
            out_dir = tmp_path / "scan_out"

            config_path.write_text(
                json.dumps(
                    {
                        "locations": ["Suzhou", "Remote"],
                        "include_keywords": ["AI", "Data"],
                        "exclude_keywords": ["Intern"],
                        "companies": [
                            {
                                "name": "Broken Workday Co",
                                "ats": "workday",
                                "url": "https://broken.wd3.myworkdayjobs.com/en-US/Careers",
                                "enabled": True,
                            },
                            {
                                "name": "Helios",
                                "ats": "greenhouse",
                                "slug": "helios",
                                "enabled": True,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            def fake_factory(provider: ATSProvider) -> Any:
                if provider == ATSProvider.WORKDAY:
                    return WorkdayAdapter(
                        transport=FakeTransport(
                            [ATSRequestError("HTTP 503", url="https://broken/jobs", status_code=503)]
                        ),
                        delay_sec=0.0,
                    )
                return GreenhouseAdapter(
                    transport=FakeTransport(
                        [
                            {
                                "jobs": [
                                    {
                                        "id": 101,
                                        "title": "Industrial AI Engineer",
                                        "location": {"name": "Suzhou, China"},
                                        "absolute_url": "https://boards.greenhouse.io/helios/jobs/101",
                                        "departments": [{"name": "AI"}],
                                        "content": "&lt;p&gt;Build agentic workflows.&lt;/p&gt;",
                                    },
                                    {
                                        "id": 102,
                                        "title": "AI Intern",
                                        "location": {"name": "Suzhou, China"},
                                        "absolute_url": "https://boards.greenhouse.io/helios/jobs/102",
                                        "departments": [{"name": "AI"}],
                                        "content": "Internship role.",
                                    },
                                ]
                            }
                        ]
                    ),
                    delay_sec=0.0,
                )

            digest = cmd_scan(
                config_path=config_path,
                db_path=db_path,
                out_dir=out_dir,
                adapter_factory=fake_factory,
            )

            self.assertEqual(len(digest["errors"]), 1)
            self.assertEqual(digest["errors"][0]["company"], "Broken Workday Co")
            self.assertEqual(len(digest["matched_new_or_updated"]), 1)
            self.assertEqual(digest["matched_new_or_updated"][0]["external_id"], "101")

            digest_file = Path(digest["digest_path"])
            self.assertTrue(digest_file.is_file())
            card_file = Path(digest["matched_new_or_updated"][0]["card_path"])
            self.assertTrue(card_file.is_file())

            status = cmd_status(db_path)
            self.assertEqual(status["active_jobs_count"], 2)
            statuses = {run["company_name"]: run["status"] for run in status["recent_scan_runs"]}
            self.assertEqual(statuses["Broken Workday Co"], "error")
            self.assertEqual(statuses["Helios"], "completed")


if __name__ == "__main__":
    unittest.main()
