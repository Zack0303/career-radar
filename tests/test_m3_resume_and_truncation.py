"""Unit tests for M3 resume selector, optional PDF renderer, and truncation-safe CLOSED tracking."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from typing import Any, Mapping, Optional

from career_radar.adapters import SmartRecruitersAdapter, WorkdayAdapter
from career_radar.cli import cmd_scan, main
from career_radar.models import ATSProvider, JobPosting, TargetCompany
from career_radar.resume import render_resume_pdf, select_projects_for_job
from career_radar.storage import SQLiteJobStore

REPO_ROOT = Path(__file__).resolve().parents[1]


class _FakeTransport:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)

    def __call__(
        self,
        method: str,
        url: str,
        payload: Optional[Mapping[str, Any]],
        headers: Optional[Mapping[str, str]],
        timeout: float,
    ) -> Any:
        return self._responses.pop(0)


class TruncationSafeClosedTests(unittest.TestCase):
    def test_smartrecruiters_and_workday_fetch_batch_completeness(self) -> None:
        # SmartRecruiters truncated when max_pages=1 but totalFound > 100 and page returned 100 items.
        sr_full_page = [
            {"id": f"SR-{i}", "name": f"Role {i}", "location": {"city": "Suzhou", "country": "cn"}}
            for i in range(100)
        ]
        sr_adapter = SmartRecruitersAdapter(
            transport=_FakeTransport([{"limit": 100, "offset": 0, "totalFound": 250, "content": sr_full_page}]),
            delay_sec=0.0,
            max_pages=1,
        )
        sr_target = TargetCompany(name="Nova", ats=ATSProvider.SMARTRECRUITERS, slug="NovaSlug")
        sr_batch = sr_adapter.fetch_batch(sr_target)
        self.assertEqual(len(sr_batch.postings), 100)
        self.assertFalse(sr_batch.is_complete)

        # SmartRecruiters complete when fewer than 100 items returned.
        sr_complete_adapter = SmartRecruitersAdapter(
            transport=_FakeTransport([{"limit": 100, "offset": 0, "totalFound": 2, "content": sr_full_page[:2]}]),
            delay_sec=0.0,
            max_pages=1,
        )
        self.assertTrue(sr_complete_adapter.fetch_batch(sr_target).is_complete)

        # Workday truncated when max_pages=1, total=45, and page returned 20 items.
        wd_full_page = [
            {
                "title": f"Engineer {i}",
                "locationsText": "Shanghai",
                "externalPath": f"/job/Shanghai/Eng_{i}",
                "bulletFields": [f"REQ-{i}"],
            }
            for i in range(20)
        ]
        wd_adapter = WorkdayAdapter(
            transport=_FakeTransport([{"total": 45, "jobPostings": wd_full_page}]),
            delay_sec=0.0,
            max_pages=1,
        )
        wd_target = TargetCompany(
            name="Apex",
            ats=ATSProvider.WORKDAY,
            url="https://apex.wd3.myworkdayjobs.com/en-US/Careers",
        )
        wd_batch = wd_adapter.fetch_batch(wd_target)
        self.assertEqual(len(wd_batch.postings), 20)
        self.assertFalse(wd_batch.is_complete)

    def test_scan_does_not_close_jobs_on_partial_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            config_path = tmp_path / "targets.json"
            db_path = tmp_path / "radar.db"
            out_dir = tmp_path / "out"
            config_path.write_text(
                json.dumps(
                    {
                        "locations": ["Suzhou"],
                        "include_keywords": ["AI"],
                        "exclude_keywords": [],
                        "companies": [
                            {
                                "name": "Nova",
                                "ats": "smartrecruiters",
                                "slug": "NovaSlug",
                                "enabled": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            store = SQLiteJobStore(db_path)
            old_job = JobPosting(
                company="Nova",
                provider=ATSProvider.SMARTRECRUITERS,
                external_id="OLD-1",
                title="AI Architect",
                location="Suzhou",
            )
            store.record_scan("Nova", ATSProvider.SMARTRECRUITERS, [old_job])

            # Partial snapshot missing OLD-1 must NOT mark OLD-1 closed.
            sr_full_page = [
                {"id": f"SR-{i}", "name": f"Role {i}", "location": {"city": "Suzhou", "country": "cn"}}
                for i in range(100)
            ]
            partial_adapter = SmartRecruitersAdapter(
                transport=_FakeTransport([{"limit": 100, "offset": 0, "totalFound": 200, "content": sr_full_page}]),
                delay_sec=0.0,
                max_pages=1,
            )
            digest_partial = cmd_scan(
                config_path=config_path,
                db_path=db_path,
                out_dir=out_dir,
                adapter_factory=lambda _p: partial_adapter,
            )
            self.assertTrue(digest_partial["companies"][0]["partial_snapshot"])
            self.assertEqual(digest_partial["companies"][0]["closed"], 0)
            active_ids = {j.external_id for j in store.list_active_jobs("Nova")}
            self.assertIn("OLD-1", active_ids)

            # Complete snapshot missing OLD-1 MUST mark OLD-1 closed.
            complete_adapter = SmartRecruitersAdapter(
                transport=_FakeTransport([{"limit": 100, "offset": 0, "totalFound": 1, "content": sr_full_page[:1]}]),
                delay_sec=0.0,
                max_pages=1,
            )
            digest_complete = cmd_scan(
                config_path=config_path,
                db_path=db_path,
                out_dir=out_dir,
                adapter_factory=lambda _p: complete_adapter,
            )
            self.assertFalse(digest_complete["companies"][0]["partial_snapshot"])
            self.assertEqual(digest_complete["companies"][0]["closed"], 100)


class ResumeSelectorAndCLITests(unittest.TestCase):
    def test_select_projects_ranks_most_relevant_and_preserves_text(self) -> None:
        demo_data = json.loads((REPO_ROOT / "templates" / "resume.demo.json").read_text(encoding="utf-8"))
        en_projects = demo_data["en"]["projects"]
        jd_text = "Build RAG workflows, tool-use checks, and regression evaluation over technical manuals."

        selected, report = select_projects_for_job(en_projects, jd_text, max_projects=1)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["name"], en_projects[0]["name"])
        self.assertEqual(selected[0]["intro"], en_projects[0]["intro"])
        self.assertTrue(report[0]["selected"])
        self.assertFalse(report[1]["selected"])

        # Now query specifically matching the second project (process analytics / approval bottlenecks).
        jd_proc = "Analyze delivery timestamps and late deliveries using SQL."
        selected2, _ = select_projects_for_job(en_projects, jd_proc, max_projects=1)
        self.assertEqual(selected2[0]["name"], en_projects[1]["name"])

    def test_cli_resume_command_bilingual_and_jd_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            out_dir = tmp_path / "resumes"
            jd_file = tmp_path / "jd.txt"
            jd_file.write_text("SQL delivery timestamps and late delivery analysis.", encoding="utf-8")

            exit_code = main(
                [
                    "resume",
                    "--resume",
                    str(REPO_ROOT / "templates" / "resume.demo.json"),
                    "--out",
                    str(out_dir),
                    "--lang",
                    "both",
                    "--format",
                    "html",
                    "--jd",
                    str(jd_file),
                    "--max-projects",
                    "1",
                ]
            )
            self.assertEqual(exit_code, 0)
            en_html = (out_dir / "alex_lin_Resume_EN.html").read_text(encoding="utf-8")
            cn_html = (out_dir / "林明_alex_lin_Resume_CN.html").read_text(encoding="utf-8")
            self.assertIn("Delivery Delay Analysis", en_html)
            self.assertNotIn("Demand Forecast Demo", en_html)
            self.assertIn("林明 (Alex Lin)", cn_html)

    def test_pdf_renderer_handles_missing_or_installed_reportlab(self) -> None:
        demo_data = json.loads((REPO_ROOT / "templates" / "resume.demo.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_out = Path(tmpdir) / "test.pdf"
            has_reportlab = importlib.util.find_spec("reportlab") is not None
            if not has_reportlab:
                with self.assertRaises(RuntimeError) as ctx:
                    render_resume_pdf(demo_data, pdf_out, lang="en")
                self.assertIn("career-radar[pdf]", str(ctx.exception))
            else:
                render_resume_pdf(demo_data, pdf_out, lang="en")
                self.assertTrue(pdf_out.read_bytes().startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
