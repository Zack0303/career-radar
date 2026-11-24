"""Command-line interface for Career Radar."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Any, Callable, Optional, Sequence

from career_radar.adapters import ATSAdapter, FixtureAdapter, get_adapter
from career_radar.matcher import (
    evaluate_job,
    parse_evidence_ids,
    render_grounded_job_card,
    render_job_card_markdown,
    validate_match_payload,
)
from career_radar.models import (
    ATSProvider,
    FilterConfig,
    JobChangeType,
    ScanError,
    TargetCompany,
)
from career_radar.resume import (
    render_resume_html,
    render_resume_pdf,
    select_projects_for_job,
)
from career_radar.storage.sqlite_store import SQLiteJobStore

_REPO_ROOT = Path(__file__).resolve().parents[2]

_INIT_TEMPLATE_MAP = (
    ("master_profile.template.md", "master_profile.md"),
    ("project_library.template.md", "project_library.md"),
    ("targets.template.json", "targets.json"),
    ("resume.demo.json", "resume.json"),
)

AdapterFactoryFn = Callable[[ATSProvider], ATSAdapter]


def cmd_init(
    workspace_dir: Path,
    templates_dir: Path,
    force: bool = False,
) -> list[Path]:
    """Copy starter templates into a git-ignored workspace directory."""
    if not templates_dir.is_dir():
        raise FileNotFoundError(f"Templates directory not found: {templates_dir}")

    workspace_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    for src_name, dst_name in _INIT_TEMPLATE_MAP:
        src = templates_dir / src_name
        dst = workspace_dir / dst_name
        if dst.exists() and not force:
            continue
        shutil.copyfile(src, dst)
        created.append(dst)
    return created


def _safe_slug(text: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in text.lower())
    return "-".join(part for part in cleaned.split("-") if part) or "job"


def _load_targets_config(
    config_path: Path,
    company_filter: Optional[str] = None,
) -> tuple[FilterConfig, list[TargetCompany]]:
    if not config_path.is_file():
        raise FileNotFoundError(f"Targets config file not found: {config_path}")
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    filter_source = raw.get("default_filters") if "default_filters" in raw else raw
    filter_config = FilterConfig.from_dict(filter_source)

    wanted_company = company_filter.strip().lower() if company_filter else ""
    targets: list[TargetCompany] = []
    for item in raw.get("companies", ()):
        if not item.get("enabled", True):
            continue
        target = TargetCompany(
            name=str(item["name"]),
            ats=ATSProvider(str(item["ats"]).strip().lower()),
            slug=str(item.get("slug", "")),
            url=str(item.get("url", "")),
            enabled=True,
            search_text=str(item.get("search_text", "")),
        )
        if wanted_company and target.name.strip().lower() != wanted_company:
            continue
        targets.append(target)
    return filter_config, targets


def cmd_scan(
    config_path: Path,
    db_path: Path,
    out_dir: Path,
    *,
    max_pages: int = 5,
    company_filter: Optional[str] = None,
    adapter_factory: Optional[AdapterFactoryFn] = None,
) -> dict[str, Any]:
    """Scan enabled official ATS targets incrementally with per-company error isolation."""
    filter_config, targets = _load_targets_config(config_path, company_filter=company_filter)
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs_dir = out_dir / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)

    store = SQLiteJobStore(db_path)
    factory: AdapterFactoryFn = adapter_factory or (
        lambda provider: get_adapter(provider, max_pages=max_pages)
    )

    company_summaries: list[dict[str, Any]] = []
    errors: list[ScanError] = []
    matched_items: list[dict[str, Any]] = []

    for target in targets:
        try:
            adapter = factory(target.ats)
            if hasattr(adapter, "fetch_batch"):
                batch = adapter.fetch_batch(target)
                postings = list(batch.postings)
                is_complete = bool(batch.is_complete)
            else:
                postings = adapter.fetch_jobs(target)
                is_complete = True
            scan_result = store.record_scan(
                target.name,
                target.ats,
                postings,
                mark_missing_closed=is_complete,
            )
        except Exception as exc:
            err_msg = str(exc)
            store.record_scan_error(target.name, target.ats, err_msg)
            errors.append(
                ScanError(
                    company_name=target.name,
                    provider=target.ats,
                    error_message=err_msg,
                )
            )
            company_summaries.append(
                {
                    "company": target.name,
                    "provider": target.ats.value,
                    "status": "error",
                    "error": err_msg,
                }
            )
            continue

        company_matched = 0
        for diff in scan_result.diffs:
            if diff.change_type not in (JobChangeType.NEW, JobChangeType.UPDATED):
                continue
            match_result = evaluate_job(diff.posting, filter_config)
            if not match_result.matched:
                continue
            company_matched += 1
            enriched = diff.posting
            if hasattr(adapter, "fetch_job_detail"):
                try:
                    enriched = adapter.fetch_job_detail(target, diff.posting)
                except Exception:
                    enriched = diff.posting
                if enriched.description != diff.posting.description:
                    store.update_job_description(
                        target.name,
                        enriched.external_id,
                        enriched.description,
                    )

            filename = f"{_safe_slug(enriched.company)}-{_safe_slug(enriched.external_id)}.md"
            card_path = jobs_dir / filename
            card_path.write_text(
                render_job_card_markdown(enriched, match_result, diff.change_type),
                encoding="utf-8",
            )
            matched_items.append(
                {
                    "company": enriched.company,
                    "provider": enriched.provider.value,
                    "external_id": enriched.external_id,
                    "change_type": diff.change_type.value,
                    "title": enriched.title,
                    "location": enriched.location,
                    "department": enriched.department,
                    "url": enriched.url,
                    "score": match_result.score,
                    "matched_keywords": list(match_result.matched_keywords),
                    "matched_locations": list(match_result.matched_locations),
                    "card_path": str(card_path),
                    "description": enriched.description,
                }
            )

        company_summaries.append(
            {
                "company": target.name,
                "provider": target.ats.value,
                "status": "completed",
                "partial_snapshot": not is_complete,
                "fetched": len(postings),
                "new": scan_result.new_count,
                "updated": scan_result.updated_count,
                "unchanged": scan_result.unchanged_count,
                "closed": scan_result.closed_count,
                "matched_new_or_updated": company_matched,
            }
        )

    digest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config_path": str(config_path),
        "db_path": str(db_path),
        "companies_targeted": len(targets),
        "companies": company_summaries,
        "errors": [
            {
                "company": err.company_name,
                "provider": err.provider.value,
                "error": err.error_message,
            }
            for err in errors
        ],
        "matched_new_or_updated": matched_items,
    }
    digest_path = out_dir / "scan_digest.json"
    digest_path.write_text(json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8")
    digest["digest_path"] = str(digest_path)
    return digest


def cmd_status(db_path: Path, *, limit: int = 20) -> dict[str, Any]:
    """Return active stored job counts and recent scan runs."""
    if not db_path.is_file():
        return {
            "db_path": str(db_path),
            "exists": False,
            "active_jobs_count": 0,
            "recent_scan_runs": [],
        }
    store = SQLiteJobStore(db_path)
    active_jobs = store.list_active_jobs()
    recent_runs = store.list_scan_runs(limit=limit)
    return {
        "db_path": str(db_path),
        "exists": True,
        "active_jobs_count": len(active_jobs),
        "recent_scan_runs": recent_runs,
    }


def cmd_apply_match(
    match_json_path: Path,
    profile_path: Path,
    projects_path: Path,
    out_card_path: Path,
) -> tuple[int, dict[str, Any]]:
    """Validate an agent-generated match JSON against source evidence and render a job card."""
    for path, label in (
        (match_json_path, "match JSON"),
        (profile_path, "master profile"),
        (projects_path, "project library"),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"Missing {label} file: {path}")

    payload = json.loads(match_json_path.read_text(encoding="utf-8"))
    source_corpus = (
        profile_path.read_text(encoding="utf-8")
        + "\n\n"
        + projects_path.read_text(encoding="utf-8")
    )
    valid_ids = parse_evidence_ids(source_corpus)
    validation = validate_match_payload(payload, valid_ids, source_corpus)

    issues_payload = [
        {"code": issue.code, "field": issue.field, "message": issue.message}
        for issue in validation.issues
    ]
    if not validation.valid:
        return 2, {"valid": False, "issues": issues_payload}

    out_card_path.parent.mkdir(parents=True, exist_ok=True)
    out_card_path.write_text(render_grounded_job_card(payload, validation), encoding="utf-8")
    return 0, {"valid": True, "card_path": str(out_card_path), "issues": []}


def cmd_resume(
    resume_json_path: Path,
    out_dir: Path,
    *,
    lang: str = "both",
    fmt: str = "html",
    jd_path: Optional[Path] = None,
    max_projects: int = 4,
) -> dict[str, Any]:
    """Build bilingual HTML/PDF resumes with optional JD-ranked project selection."""
    if lang not in ("en", "cn", "both"):
        raise ValueError(f"Unsupported lang '{lang}'; choose en, cn, or both.")
    if fmt not in ("html", "pdf", "both"):
        raise ValueError(f"Unsupported format '{fmt}'; choose html, pdf, or both.")
    if not resume_json_path.is_file():
        raise FileNotFoundError(f"Resume JSON file not found: {resume_json_path}")

    jd_text: Optional[str] = None
    if jd_path is not None:
        if not jd_path.is_file():
            raise FileNotFoundError(f"JD file not found: {jd_path}")
        jd_text = jd_path.read_text(encoding="utf-8")

    raw_data = json.loads(resume_json_path.read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)

    target_langs = ("en", "cn") if lang == "both" else (lang,)
    outputs: list[str] = []
    selected_projects: dict[str, Any] = {}

    for lang_code in target_langs:
        if lang_code in raw_data and isinstance(raw_data[lang_code], dict):
            lang_payload = dict(raw_data[lang_code])
        else:
            lang_payload = dict(raw_data)

        if jd_text is not None and isinstance(lang_payload.get("projects"), list):
            chosen, report = select_projects_for_job(
                lang_payload["projects"],
                jd_text,
                max_projects=max_projects,
            )
            lang_payload["projects"] = chosen
            selected_projects[lang_code] = report

        name_slug = _safe_slug(str(lang_payload.get("name") or "candidate")).replace("-", "_")
        base_name = f"{name_slug}_Resume_{lang_code.upper()}"

        if fmt in ("html", "both"):
            html_path = out_dir / f"{base_name}.html"
            html_path.write_text(render_resume_html(lang_payload, lang=lang_code), encoding="utf-8")
            outputs.append(str(html_path))

        if fmt in ("pdf", "both"):
            pdf_path = out_dir / f"{base_name}.pdf"
            render_resume_pdf(lang_payload, pdf_path, lang=lang_code)
            outputs.append(str(pdf_path))

    return {
        "outputs": outputs,
        "selected_projects": selected_projects,
        "jd_used": str(jd_path) if jd_path is not None else None,
    }


def cmd_demo(
    out_dir: Path,
    fixture_path: Path,
    resume_path: Path,
) -> dict[str, object]:
    """Run the complete offline M0 vertical slice over fictional demo data."""
    if not fixture_path.is_file():
        raise FileNotFoundError(f"Fixture file not found: {fixture_path}")
    if not resume_path.is_file():
        raise FileNotFoundError(f"Resume JSON file not found: {resume_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "career_radar.db"
    jobs_dir = out_dir / "jobs"
    resumes_dir = out_dir / "resumes"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    resumes_dir.mkdir(parents=True, exist_ok=True)

    adapter = FixtureAdapter(fixture_path)
    postings = adapter.fetch_jobs(TargetCompany(name="*", ats=ATSProvider.FIXTURE))

    by_company = defaultdict(list)
    for posting in postings:
        by_company[posting.company].append(posting)

    store = SQLiteJobStore(db_path)
    first_pass = [
        store.record_scan(company, items[0].provider, items)
        for company, items in by_company.items()
    ]
    second_pass = [
        store.record_scan(company, items[0].provider, items)
        for company, items in by_company.items()
    ]

    filter_config = FilterConfig(
        locations=("Guangzhou", "Shenzhen", "Remote"),
        include_keywords=("Data", "Operations", "Analyst"),
        exclude_keywords=("Intern",),
    )

    matched_cards: list[Path] = []
    excluded_titles: list[str] = []
    for scan_result in first_pass:
        for diff in scan_result.diffs:
            match_result = evaluate_job(diff.posting, filter_config)
            if match_result.matched:
                filename = f"{_safe_slug(diff.posting.company)}-{_safe_slug(diff.posting.external_id)}.md"
                card_path = jobs_dir / filename
                card_path.write_text(
                    render_job_card_markdown(diff.posting, match_result, diff.change_type),
                    encoding="utf-8",
                )
                matched_cards.append(card_path)
            else:
                excluded_titles.append(diff.posting.title)

    resume_data = json.loads(resume_path.read_text(encoding="utf-8"))
    en_path = resumes_dir / "Alex_Lin_Resume_EN.html"
    cn_path = resumes_dir / "Lin_Ming_Resume_CN.html"
    en_path.write_text(render_resume_html(resume_data, lang="en"), encoding="utf-8")
    cn_path.write_text(render_resume_html(resume_data, lang="cn"), encoding="utf-8")

    return {
        "db_path": str(db_path),
        "first_scan_new": sum(res.new_count for res in first_pass),
        "second_scan_unchanged": sum(res.unchanged_count for res in second_pass),
        "matched_cards": [str(path) for path in matched_cards],
        "excluded_titles": excluded_titles,
        "resumes": [str(en_path), str(cn_path)],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="career-radar",
        description="Local-first official ATS job radar and evidence-grounded resume kit.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize private workspace templates.")
    init_parser.add_argument("--dir", default="workspace", help="Target workspace directory.")
    init_parser.add_argument(
        "--templates-dir",
        default=str(_REPO_ROOT / "templates"),
        help="Path to templates directory.",
    )
    init_parser.add_argument("--force", action="store_true", help="Overwrite existing workspace files.")

    scan_parser = subparsers.add_parser("scan", help="Scan enabled official ATS targets incrementally.")
    scan_parser.add_argument(
        "--config",
        default="workspace/targets.json",
        help="Path to targets configuration JSON.",
    )
    scan_parser.add_argument(
        "--db",
        default="workspace/career_radar.db",
        help="Path to SQLite database.",
    )
    scan_parser.add_argument(
        "--out",
        default="output/scan",
        help="Output directory for job cards and scan_digest.json.",
    )
    scan_parser.add_argument(
        "--max-pages",
        type=int,
        default=5,
        help="Maximum paginated requests per paginated ATS provider.",
    )
    scan_parser.add_argument(
        "--company",
        default=None,
        help="Optional exact company name filter (case-insensitive).",
    )

    status_parser = subparsers.add_parser("status", help="Inspect active jobs and recent scan runs.")
    status_parser.add_argument(
        "--db",
        default="workspace/career_radar.db",
        help="Path to SQLite database.",
    )
    status_parser.add_argument("--limit", type=int, default=20, help="Max scan runs to display.")

    apply_parser = subparsers.add_parser(
        "apply-match",
        help="Validate a grounded match JSON against profile/project evidence and write a job card.",
    )
    apply_parser.add_argument("--match-json", required=True, help="Path to agent-generated match JSON.")
    apply_parser.add_argument(
        "--profile",
        default="workspace/master_profile.md",
        help="Path to master_profile.md.",
    )
    apply_parser.add_argument(
        "--projects",
        default="workspace/project_library.md",
        help="Path to project_library.md.",
    )
    apply_parser.add_argument("--out", required=True, help="Output Markdown job card path.")

    resume_parser = subparsers.add_parser(
        "resume",
        help="Render bilingual HTML/PDF resumes with optional JD-based project selection.",
    )
    resume_parser.add_argument(
        "--resume",
        default="workspace/resume.json",
        help="Path to structured resume JSON.",
    )
    resume_parser.add_argument(
        "--out",
        default="output/resumes",
        help="Output directory for generated resume files.",
    )
    resume_parser.add_argument(
        "--lang",
        choices=["en", "cn", "both"],
        default="both",
        help="Target resume language(s).",
    )
    resume_parser.add_argument(
        "--format",
        choices=["html", "pdf", "both"],
        default="html",
        help="Output format(s).",
    )
    resume_parser.add_argument(
        "--jd",
        default=None,
        help="Optional JD text/Markdown path to rank and select top projects.",
    )
    resume_parser.add_argument(
        "--max-projects",
        type=int,
        default=4,
        help="Maximum projects to include when --jd selection runs.",
    )

    demo_parser = subparsers.add_parser("demo", help="Run offline M0 demo on fictional data.")
    demo_parser.add_argument("--out", default="output/demo", help="Output directory for demo artifacts.")
    demo_parser.add_argument(
        "--fixture",
        default=str(_REPO_ROOT / "examples" / "demo_jobs_fixture.json"),
        help="Path to synthetic jobs JSON fixture.",
    )
    demo_parser.add_argument(
        "--resume",
        default=str(_REPO_ROOT / "templates" / "resume.demo.json"),
        help="Path to bilingual resume JSON file.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "init":
        created = cmd_init(
            workspace_dir=Path(args.dir),
            templates_dir=Path(args.templates_dir),
            force=bool(args.force),
        )
        print(f"Initialized workspace '{args.dir}' ({len(created)} files created).")
        for path in created:
            print(f"  - {path}")
        return 0

    if args.command == "scan":
        digest = cmd_scan(
            config_path=Path(args.config),
            db_path=Path(args.db),
            out_dir=Path(args.out),
            max_pages=int(args.max_pages),
            company_filter=args.company,
        )
        print(json.dumps(digest, ensure_ascii=False, indent=2))
        return 0

    if args.command == "status":
        summary = cmd_status(db_path=Path(args.db), limit=int(args.limit))
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    if args.command == "apply-match":
        code, result = cmd_apply_match(
            match_json_path=Path(args.match_json),
            profile_path=Path(args.profile),
            projects_path=Path(args.projects),
            out_card_path=Path(args.out),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code

    if args.command == "resume":
        summary = cmd_resume(
            resume_json_path=Path(args.resume),
            out_dir=Path(args.out),
            lang=str(args.lang),
            fmt=str(args.format),
            jd_path=Path(args.jd) if args.jd else None,
            max_projects=int(args.max_projects),
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    if args.command == "demo":
        summary = cmd_demo(
            out_dir=Path(args.out),
            fixture_path=Path(args.fixture),
            resume_path=Path(args.resume),
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    return 1
