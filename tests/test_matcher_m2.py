"""Unit tests for M2 word-boundary matching, detail enrichment, and evidence validation."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from typing import Any, Mapping, Optional

from career_radar.adapters import ATSRequestError, SmartRecruitersAdapter, WorkdayAdapter
from career_radar.cli import cmd_apply_match, cmd_scan, main
from career_radar.matcher import (
    evaluate_job,
    parse_evidence_ids,
    validate_match_payload,
)
from career_radar.models import ATSProvider, FilterConfig, JobPosting, TargetCompany
from career_radar.storage import SQLiteJobStore


class _SequenceTransport:
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
        self.calls.append({"method": method, "url": url})
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


class WordBoundaryMatcherTests(unittest.TestCase):
    def test_ascii_word_boundaries_prevent_substring_false_positives(self) -> None:
        config = FilterConfig(
            locations=("Shanghai", "Suzhou"),
            include_keywords=("AI", "智能体"),
            exclude_keywords=("Intern",),
        )

        # Should NOT match "AI" inside "Shanghai" or "Training".
        training_head = JobPosting(
            company="TestCo",
            provider=ATSProvider.SMARTRECRUITERS,
            external_id="1",
            title="Operation Head of Training Center",
            location="Suzhou, China",
            description="Working Location: Shanghai",
        )
        self.assertFalse(evaluate_job(training_head, config).matched)

        # Should match standalone/mixed CJK-ASCII "工业AI智能体架构师".
        mixed_ai = JobPosting(
            company="TestCo",
            provider=ATSProvider.SMARTRECRUITERS,
            external_id="2",
            title="工业AI智能体架构师",
            location="Suzhou, China",
            description="Agentic AI systems",
        )
        res_mixed = evaluate_job(mixed_ai, config)
        self.assertTrue(res_mixed.matched)
        self.assertEqual(set(res_mixed.matched_keywords), {"AI", "智能体"})

        # Exclude "Intern" should NOT exclude "Internal Systems".
        internal_role = JobPosting(
            company="TestCo",
            provider=ATSProvider.SMARTRECRUITERS,
            external_id="3",
            title="AI Engineer for Internal Systems",
            location="Shanghai, China",
            description="Internal tooling",
        )
        self.assertTrue(evaluate_job(internal_role, config).matched)


class DetailEnrichmentTests(unittest.TestCase):
    def test_smartrecruiters_and_workday_detail_preserve_content_hash(self) -> None:
        sr_transport = _SequenceTransport(
            [
                {
                    "jobAd": {
                        "sections": {
                            "jobDescription": {"text": "&lt;p&gt;Build &amp; deploy AI pipelines.&lt;/p&gt;"},
                            "qualifications": {"text": "<ul><li>Python 3+</li></ul>"},
                        }
                    }
                }
            ]
        )
        sr = SmartRecruitersAdapter(transport=sr_transport, delay_sec=0.0)
        sr_target = TargetCompany(name="Nova", ats=ATSProvider.SMARTRECRUITERS, slug="NovaSlug")
        base_sr = JobPosting(
            company="Nova",
            provider=ATSProvider.SMARTRECRUITERS,
            external_id="SR-9",
            title="AI Engineer",
            location="Suzhou",
            description="summary",
        )
        enriched_sr = sr.fetch_job_detail(sr_target, base_sr)
        self.assertEqual(enriched_sr.content_hash, base_sr.content_hash)
        self.assertIn("Build & deploy AI pipelines.", enriched_sr.description)
        self.assertIn("- Python 3+", enriched_sr.description)

        wd_transport = _SequenceTransport(
            [{"jobPostingInfo": {"jobDescription": "<p>Design QMS RAG harness.</p>"}}]
        )
        wd = WorkdayAdapter(transport=wd_transport, delay_sec=0.0)
        wd_target = TargetCompany(
            name="Apex",
            ats=ATSProvider.WORKDAY,
            url="https://apex.wd3.myworkdayjobs.com/en-US/Careers",
        )
        base_wd = JobPosting(
            company="Apex",
            provider=ATSProvider.WORKDAY,
            external_id="REQ-9",
            title="LLM Engineer",
            location="Shanghai",
            description="REQ-9",
            raw_payload={"externalPath": "/job/Shanghai/LLM-Engineer_REQ-9"},
        )
        enriched_wd = wd.fetch_job_detail(wd_target, base_wd)
        self.assertEqual(enriched_wd.content_hash, base_wd.content_hash)
        self.assertEqual(enriched_wd.description, "Design QMS RAG harness.")
        self.assertTrue(
            wd_transport.calls[0]["url"].endswith("/wday/cxs/apex/Careers/job/Shanghai/LLM-Engineer_REQ-9")
        )

    def test_scan_enriches_matched_jd_and_survives_detail_failure(self) -> None:
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

            transport = _SequenceTransport(
                [
                    # Scan 1 list + detail (fails gracefully)
                    {
                        "limit": 100,
                        "offset": 0,
                        "totalFound": 1,
                        "content": [
                            {
                                "id": "SR-1",
                                "name": "AI Engineer",
                                "location": {"city": "Suzhou", "country": "cn", "remote": False},
                            }
                        ],
                    },
                    ATSRequestError("detail timeout", url="https://example/detail", status_code=504),
                ]
            )
            adapter = SmartRecruitersAdapter(transport=transport, delay_sec=0.0)
            digest1 = cmd_scan(
                config_path=config_path,
                db_path=db_path,
                out_dir=out_dir,
                adapter_factory=lambda _p: adapter,
            )
            self.assertEqual(digest1["errors"], [])
            self.assertEqual(len(digest1["matched_new_or_updated"]), 1)

            # Scan 2 with identical list response must stay UNCHANGED even if Scan 1 enriched description.
            transport2 = _SequenceTransport(
                [
                    {
                        "limit": 100,
                        "offset": 0,
                        "totalFound": 1,
                        "content": [
                            {
                                "id": "SR-1",
                                "name": "AI Engineer",
                                "location": {"city": "Suzhou", "country": "cn", "remote": False},
                            }
                        ],
                    }
                ]
            )
            adapter2 = SmartRecruitersAdapter(transport=transport2, delay_sec=0.0)
            SQLiteJobStore(db_path).update_job_description("Nova", "SR-1", "Full JD text")
            digest2 = cmd_scan(
                config_path=config_path,
                db_path=db_path,
                out_dir=out_dir,
                adapter_factory=lambda _p: adapter2,
            )
            self.assertEqual(digest2["companies"][0]["unchanged"], 1)
            self.assertEqual(digest2["companies"][0]["updated"], 0)


class EvidenceValidatorAndCLITests(unittest.TestCase):
    SOURCE_DOC = """
# Project Library
| **P1** | Data Pipeline | SQL | `[Self-reported]` |
### P3. Retrieval Prototype
Achieved 99.5% citation presence across 12 fixed test cases.
"""

    def _valid_payload(self) -> dict[str, Any]:
        return {
            "company": "Nova Robotics",
            "external_id": "SR-1001",
            "title": "Industrial AI Engineer",
            "location": "Suzhou",
            "url": "https://careers.example.com/SR-1001",
            "fit_level": "high",
            "matched_evidence": [
                {
                    "evidence_id": "P3",
                    "level": "verified",
                    "claim": "Built retrieval prototype achieving 99.5% citation presence (P3).",
                }
            ],
            "gaps": ["No production Kubernetes experience."],
            "questions_to_ask": ["Confirm edge vs cloud ownership."],
            "recruiter_brief": {
                "role": "Industrial AI Engineer",
                "company": "Nova Robotics",
                "fit_summary": "Strong match in data pipelines and grounded LLM workflows.",
                "evidence_points": ["P3: 99.5% citation presence in fixed regression checks"],
                "location_availability": "Suzhou / full-time",
                "open_gaps": "Production Kubernetes scaling not demonstrated.",
            },
        }

    def test_parse_evidence_ids_and_validation_rules(self) -> None:
        valid_ids = parse_evidence_ids(self.SOURCE_DOC)
        self.assertEqual(valid_ids, {"P1", "P3"})

        good = self._valid_payload()
        res_good = validate_match_payload(good, valid_ids, self.SOURCE_DOC)
        self.assertTrue(res_good.valid, res_good.issues)

        bad_id = self._valid_payload()
        bad_id["matched_evidence"][0]["evidence_id"] = "P99"
        res_bad_id = validate_match_payload(bad_id, valid_ids, self.SOURCE_DOC)
        self.assertFalse(res_bad_id.valid)
        self.assertEqual(res_bad_id.issues[0].code, "UNKNOWN_EVIDENCE_ID")

        bad_level = self._valid_payload()
        bad_level["matched_evidence"][0]["level"] = "gap"
        res_bad_level = validate_match_payload(bad_level, valid_ids, self.SOURCE_DOC)
        self.assertFalse(res_bad_level.valid)
        self.assertEqual(res_bad_level.issues[0].code, "INVALID_EVIDENCE_LEVEL")

        hallucinated_num = self._valid_payload()
        hallucinated_num["matched_evidence"][0]["claim"] = "Reduced audit time by 45% (P1)."
        hallucinated_num["matched_evidence"][0]["evidence_id"] = "P1"
        res_num = validate_match_payload(hallucinated_num, valid_ids, self.SOURCE_DOC)
        self.assertFalse(res_num.valid)
        self.assertTrue(any(i.code == "UNGROUNDED_NUMERIC_CLAIM" for i in res_num.issues))

    def test_cli_apply_match_blocks_invalid_and_writes_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            profile = tmp_path / "master_profile.md"
            projects = tmp_path / "project_library.md"
            match_json = tmp_path / "match.json"
            out_card = tmp_path / "card.md"

            profile.write_text("# Profile\nExperienced in SQL pipelines.\n", encoding="utf-8")
            projects.write_text(self.SOURCE_DOC, encoding="utf-8")

            invalid_payload = self._valid_payload()
            invalid_payload["recruiter_brief"]["evidence_points"] = ["P3: Cut latency by 80%"]
            match_json.write_text(json.dumps(invalid_payload), encoding="utf-8")

            code_fail = main(
                [
                    "apply-match",
                    "--match-json",
                    str(match_json),
                    "--profile",
                    str(profile),
                    "--projects",
                    str(projects),
                    "--out",
                    str(out_card),
                ]
            )
            self.assertEqual(code_fail, 2)
            self.assertFalse(out_card.exists())

            valid_payload = self._valid_payload()
            match_json.write_text(json.dumps(valid_payload), encoding="utf-8")
            code_ok, result = cmd_apply_match(match_json, profile, projects, out_card)
            self.assertEqual(code_ok, 0)
            self.assertTrue(result["valid"])
            card_text = out_card.read_text(encoding="utf-8")
            self.assertIn("Evidence Validation**: `PASSED`", card_text)
            self.assertIn("## Recruiter Brief (5-Line Shareable Summary)", card_text)


if __name__ == "__main__":
    unittest.main()
