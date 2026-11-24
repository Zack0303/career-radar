# Changelog

## v0.1.0 (2026-11-24)

Initial public release covering Milestones M0–M3 and CI/workflow packaging.

### Added
- **Official ATS Adapters (`M1`)**: Pure-stdlib HTTP fetchers and normalizers for SmartRecruiters, Greenhouse, Lever, and Workday CXS (`limit=20` enforced), plus offline `FixtureAdapter`.
- **Incremental SQLite Store (`M0/M1/M3`)**: Deterministic SHA-256 content hashing tracking `NEW`, `UPDATED`, `UNCHANGED`, and `CLOSED` job transitions, per-company error isolation (`status='error'`), and truncation-safe `FetchBatch` guarding so partial `--max-pages` scans never mark unseen roles as closed.
- **Stage-1 Filter & On-Demand Full JD Enrichment (`M2`)**: ASCII word-boundary keyword matching (preventing false positives such as `"AI"` inside `"Shanghai"` or `"Training"`), plus on-demand full JD fetching for matched SmartRecruiters and Workday roles.
- **Anti-Hallucination Evidence Validator (`M2`)**: `apply-match` CLI and `evidence_validator.py` enforcing explicit `P1..Pn` evidence IDs, allowed evidence levels (`verified`, `self_reported`), source-grounded numeric claims, and a 5-line `Recruiter Brief`.
- **Bring-Your-Own-Agent Skill (`M2`)**: `skills/career-radar-matcher/SKILL.md` enabling `$0` extra API cost matching with Antigravity, Claude Code, and Codex.
- **Bilingual A4 Resume Builder (`M0/M3`)**: Deterministic JD-ranked project selector (`select_projects_for_job`), zero-dependency EN/CN A4 HTML renderer, optional ReportLab PDF exporter (`[pdf]`), and `resume` CLI.
- **Templates, Presets & Workflows**: Sanitized `master_profile` / `project_library` templates, starter presets, genuine `apply-match` sample card (`examples/sample_grounded_job_card.md`), MIT `LICENSE`, and GitHub Actions templates (`ci.yml`, `daily-scan.yml`).

### Known Boundaries
- `Siemens` (`jobs.siemens.com`) and `Mistral AI` (`api.lever.co/v0/postings/mistral`) remain disabled (`needs_check`) in starter presets after failing M1 smoke checks.
- Read-only MCP Server and headless LLM API fallback remain planned for `v0.2`.
