"""Automated unit and end-to-end CLI tests for Career Radar M0."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from career_radar.adapters import (
    FixtureAdapter,
    GreenhouseAdapter,
    LeverAdapter,
    SmartRecruitersAdapter,
    WorkdayAdapter,
)
from career_radar.cli import main
from career_radar.matcher import evaluate_job, render_job_card_markdown
from career_radar.models import (
    ATSProvider,
    FilterConfig,
    JobChangeType,
    JobPosting,
    TargetCompany,
)
from career_radar.resume import render_resume_html
from career_radar.storage import SQLiteJobStore

REPO_ROOT = Path(__file__).resolve().parents[1]


class ModelsAndAdaptersTests(unittest.TestCase):
    def test_content_hash_is_deterministic_across_whitespace(self) -> None:
        p1 = JobPosting(
            company="Nova Robotics",
            provider=ATSProvider.SMARTRECRUITERS,
            external_id="101",
            title="AI Engineer",
            location="Suzhou",
            description="Line 1\r\nLine 2  ",
        )
        p2 = JobPosting(
            company="Nova Robotics",
            provider=ATSProvider.SMARTRECRUITERS,
            external_id="101",
            title="  AI Engineer ",
            location="Suzhou",
            description="Line 1\nLine 2",
        )
        p3 = JobPosting(
            company="Nova Robotics",
            provider=ATSProvider.SMARTRECRUITERS,
            external_id="101",
            title="Senior AI Engineer",
            location="Suzhou",
            description="Line 1\nLine 2",
        )
        self.assertEqual(p1.content_hash, p2.content_hash)
        self.assertNotEqual(p1.content_hash, p3.content_hash)

    def test_live_adapters_build_endpoints(self) -> None:
        sr = SmartRecruitersAdapter()
        sr_target = TargetCompany(name="Nova", ats=ATSProvider.SMARTRECRUITERS, slug="NovaSlug")
        self.assertEqual(
            sr.build_endpoint(sr_target),
            "https://api.smartrecruiters.com/v1/companies/NovaSlug/postings",
        )

        gh = GreenhouseAdapter()
        gh_target = TargetCompany(name="Helios", ats=ATSProvider.GREENHOUSE, slug="helios")
        self.assertEqual(
            gh.build_endpoint(gh_target),
            "https://boards-api.greenhouse.io/v1/boards/helios/jobs?content=true",
        )

        lv = LeverAdapter()
        lv_target = TargetCompany(name="Meridian", ats=ATSProvider.LEVER, slug="meridian")
        self.assertEqual(
            lv.build_endpoint(lv_target),
            "https://api.lever.co/v0/postings/meridian?mode=json",
        )

        wd = WorkdayAdapter()
        wd_target = TargetCompany(
            name="Apex",
            ats=ATSProvider.WORKDAY,
            url="https://apex.wd3.myworkdayjobs.com/en-US/Careers",
        )
        self.assertEqual(
            wd.build_endpoint(wd_target),
            "https://apex.wd3.myworkdayjobs.com/wday/cxs/apex/Careers/jobs",
        )

    def test_fixture_adapter_filters_by_company(self) -> None:
        adapter = FixtureAdapter(REPO_ROOT / "examples" / "demo_jobs_fixture.json")
        all_jobs = adapter.fetch_jobs(TargetCompany(name="*", ats=ATSProvider.FIXTURE))
        nova_jobs = adapter.fetch_jobs(TargetCompany(name="Nova Robotics", ats=ATSProvider.FIXTURE))
        self.assertEqual(len(all_jobs), 4)
        self.assertEqual(len(nova_jobs), 1)
        self.assertEqual(nova_jobs[0].external_id, "SR-1001")


class SQLiteIncrementalStoreTests(unittest.TestCase):
    def test_new_unchanged_updated_closed_and_reactivated_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SQLiteJobStore(Path(tmpdir) / "jobs.db")
            j1 = JobPosting(
                company="Nova Robotics",
                provider=ATSProvider.SMARTRECRUITERS,
                external_id="J1",
                title="AI Engineer",
                location="Suzhou",
                description="v1",
            )
            j2 = JobPosting(
                company="Nova Robotics",
                provider=ATSProvider.SMARTRECRUITERS,
                external_id="J2",
                title="Data Engineer",
                location="Shanghai",
                description="v1",
            )

            r1 = store.record_scan("Nova Robotics", ATSProvider.SMARTRECRUITERS, [j1, j2])
            self.assertEqual((r1.new_count, r1.updated_count, r1.unchanged_count, r1.closed_count), (2, 0, 0, 0))

            r2 = store.record_scan("Nova Robotics", ATSProvider.SMARTRECRUITERS, [j1, j2])
            self.assertEqual((r2.new_count, r2.updated_count, r2.unchanged_count, r2.closed_count), (0, 0, 2, 0))

            j1_v2 = JobPosting(
                company="Nova Robotics",
                provider=ATSProvider.SMARTRECRUITERS,
                external_id="J1",
                title="AI Engineer",
                location="Suzhou",
                description="v2 updated scope",
            )
            j3 = JobPosting(
                company="Nova Robotics",
                provider=ATSProvider.SMARTRECRUITERS,
                external_id="J3",
                title="ML Ops Engineer",
                location="Remote",
                description="v1",
            )
            r3 = store.record_scan("Nova Robotics", ATSProvider.SMARTRECRUITERS, [j1_v2, j3])
            self.assertEqual((r3.new_count, r3.updated_count, r3.unchanged_count, r3.closed_count), (1, 1, 0, 1))
            active_ids = {job.external_id for job in store.list_active_jobs("Nova Robotics")}
            self.assertEqual(active_ids, {"J1", "J3"})

            # Re-opening previously closed J2 should reactivate it cleanly.
            r4 = store.record_scan("Nova Robotics", ATSProvider.SMARTRECRUITERS, [j1_v2, j2, j3])
            self.assertEqual((r4.new_count, r4.updated_count, r4.unchanged_count, r4.closed_count), (0, 1, 2, 0))
            events = store.list_events("Nova Robotics")
            self.assertEqual(events[-1]["event_type"], JobChangeType.UPDATED.value)
            self.assertEqual(events[-1]["external_id"], "J2")


class RuleMatcherAndResumeTests(unittest.TestCase):
    def test_rule_matcher_location_include_and_exclude(self) -> None:
        config = FilterConfig(
            locations=("Guangzhou", "Shenzhen", "Remote"),
            include_keywords=("Operations", "Data"),
            exclude_keywords=("Intern",),
        )
        adapter = FixtureAdapter(REPO_ROOT / "examples" / "demo_jobs_fixture.json")
        postings = {p.external_id: p for p in adapter.load_all()}

        sr_match = evaluate_job(postings["SR-1001"], config)
        self.assertTrue(sr_match.matched)
        self.assertGreater(sr_match.score, 0)

        intern_match = evaluate_job(postings["GH-3099"], config)
        self.assertFalse(intern_match.matched)
        self.assertEqual(intern_match.score, 0)
        self.assertIn("Intern", intern_match.excluded_keywords)

        card_md = render_job_card_markdown(postings["SR-1001"], sr_match, JobChangeType.NEW)
        self.assertIn("## Recruiter Brief (5-Line Shareable Summary)", card_md)
        self.assertIn("Pending M2", card_md)

    def test_bilingual_resume_renderer_and_html_escaping(self) -> None:
        demo_data = json.loads((REPO_ROOT / "templates" / "resume.demo.json").read_text(encoding="utf-8"))
        en_html = render_resume_html(demo_data, lang="en")
        cn_html = render_resume_html(demo_data, lang="cn")

        self.assertIn("<html lang=\"en\">", en_html)
        self.assertIn("Alex Lin", en_html)
        self.assertIn("Summary", en_html)
        self.assertIn("<html lang=\"zh-CN\">", cn_html)
        self.assertIn("林明 (Alex Lin)", cn_html)
        self.assertIn("个人简介", cn_html)

        xss_payload = json.loads(json.dumps(demo_data["en"]))
        xss_payload["name"] = "<script>alert(1)</script>"
        escaped_html = render_resume_html(xss_payload, lang="en")
        self.assertNotIn("<script>", escaped_html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", escaped_html)


class CLIEndToEndTests(unittest.TestCase):
    def test_init_and_demo_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            ws_dir = tmp_path / "workspace"
            out_dir = tmp_path / "demo_out"

            exit_init = main(["init", "--dir", str(ws_dir)])
            self.assertEqual(exit_init, 0)
            self.assertTrue((ws_dir / "master_profile.md").is_file())
            self.assertTrue((ws_dir / "project_library.md").is_file())
            self.assertTrue((ws_dir / "targets.json").is_file())
            self.assertTrue((ws_dir / "resume.json").is_file())

            # Second init without --force must preserve user edits.
            (ws_dir / "master_profile.md").write_text("USER CUSTOM", encoding="utf-8")
            self.assertEqual(main(["init", "--dir", str(ws_dir)]), 0)
            self.assertEqual((ws_dir / "master_profile.md").read_text(encoding="utf-8"), "USER CUSTOM")

            exit_demo = main(["demo", "--out", str(out_dir)])
            self.assertEqual(exit_demo, 0)
            self.assertTrue((out_dir / "career_radar.db").is_file())
            self.assertEqual(len(list((out_dir / "jobs").glob("*.md"))), 3)
            self.assertTrue((out_dir / "resumes" / "Alex_Lin_Resume_EN.html").is_file())
            self.assertTrue((out_dir / "resumes" / "Lin_Ming_Resume_CN.html").is_file())


if __name__ == "__main__":
    unittest.main()
