# Getting started with Career Radar

[Home](../README.md) · [中文首页](../README_ZH.md)

This guide uses commands for macOS/Linux from the repository root. On Windows PowerShell, run `$env:PYTHONPATH = "src"` once per shell and omit `PYTHONPATH=src` from each command; use `python` if that is your Python command.

## 1. Try the fictional demo

```bash
git clone https://github.com/Zack0303/career-radar.git
cd career-radar
PYTHONPATH=src python3 -m career_radar demo --out output/demo
```

Open `output/demo/jobs/` for rule-filtered fictional cards and `output/demo/resumes/` for the fictional English and Chinese HTML resumes. The demo uses its own SQLite file and does not scan the internet.

## 2. Create your private workspace

```bash
PYTHONPATH=src python3 -m career_radar init --dir workspace
```

This copies templates without overwriting existing files. It creates `targets.json`, `master_profile.md`, `project_library.md`, and `resume.json`. The resume initially contains fictional data: replace it with your own before using it. Do not commit or share private files. `.gitignore` is a useful guard, not encryption or a complete privacy guarantee.

## 3. Configure official company boards

Edit `workspace/targets.json`. This is an illustrative structure, not a working company configuration:

```json
{
  "locations": ["Guangzhou", "Shenzhen", "Remote"],
  "include_keywords": ["Data", "Operations", "Analyst"],
  "exclude_keywords": ["Intern"],
  "companies": [
    {"name": "Example company", "ats": "greenhouse", "slug": "replace-with-real-board-token", "enabled": true}
  ]
}
```

- `locations` matches part of the reported location, case-insensitively. An empty array does not filter by location.
- `include_keywords` requires at least one match in the title, department, or description; an empty array does not require one. `exclude_keywords` rejects any matching term. ASCII keywords use word boundaries.
- `companies` lists the boards to scan. Remove the example placeholders or set them to `"enabled": false`. `name` is a label; `ats` is one of `smartrecruiters`, `greenhouse`, `lever`, or `workday`.
- For Greenhouse, Lever and SmartRecruiters, `slug` is the board/company identifier used by that provider. For a standard Workday board, use `"url"` instead, with the full public board URL ending in its site name. Find these from a company's official careers site; branded or customized sites may not expose a compatible endpoint. Never assume an unverified URL works.
- The presets in `presets/` are examples of target configuration, not a guarantee that endpoints still work. Companies marked `needs_check` are disabled.

## 4. Scan and inspect

```bash
PYTHONPATH=src python3 -m career_radar scan \
  --config workspace/targets.json \
  --db workspace/career_radar.db \
  --out output/scan --max-pages 5

PYTHONPATH=src python3 -m career_radar status --db workspace/career_radar.db
```

The scan writes `output/scan/scan_digest.json`, company results, and Markdown cards for matching **new or updated** postings. Check `errors` and each company's `status` in the digest even if the command completes. Individual company failures do not stop the rest of the scan. `partial_snapshot: true` means the pagination limit or provider response may have prevented a full scan; unseen jobs are not marked closed for that company.

Run again with the same database to compare results. It is normal to see no new cards when nothing has changed. Change filters or company endpoints deliberately and inspect results. The tool is not a complete index of all job openings.

## 5. Optional: assess evidence with an assistant

Replace the placeholders in `workspace/master_profile.md` and `workspace/project_library.md` with your own information. Before giving files to any AI assistant, review its privacy settings and remove anything you do not want to share. Ask the assistant to follow [the matcher instructions](../skills/career-radar-matcher/SKILL.md) and produce a match JSON for one job. Review its claims and keep private constraints out of shareable text.

Validate the result (replace the JSON path with the one produced by your assistant):

```bash
PYTHONPATH=src python3 -m career_radar apply-match \
  --match-json output/scan/match.json \
  --profile workspace/master_profile.md \
  --projects workspace/project_library.md \
  --out output/scan/jobs/verified-card.md
```

Exit code `2` signals validation issues. The checks are limited: existing IDs, allowed levels, some numeric tokens in the source corpus, and the required structure. They cannot establish truth or ensure a claim is supported by its cited project. Read and correct the full output yourself. The [fictional match JSON](../examples/demo_match.json), [source evidence](../examples/demo_evidence.md), and [rendered card](../examples/sample_grounded_job_card.md) show the format.

## 6. Generate a resume

Edit `workspace/resume.json` to replace **all** fictional sample details. Point `--jd` at a local job description or card:

```bash
PYTHONPATH=src python3 -m career_radar resume \
  --resume workspace/resume.json --out output/resumes \
  --lang both --format html \
  --jd output/scan/jobs/verified-card.md --max-projects 3
```

Open the HTML files in a browser and use print-to-PDF if desired. The optional direct PDF renderer needs ReportLab installed in your chosen Python environment (`python3 -m pip install reportlab`) and `--format pdf`. The selection is keyword-based and does not assess the truth of your resume.

## Troubleshooting

- **No jobs:** check configured locations, keywords, enabled company entries and pagination; a repeated scan emits cards for new or changed matches only.
- **Company error:** read its error in `scan_digest.json`, then check the official ATS address, token, provider and connectivity. Some company endpoints may be unsupported or change.
- **No `match.json`:** it is generated by your chosen assistant, not by `scan`. Matching is optional.
- **Validation passed but a claim looks wrong:** correct it anyway. The checker cannot verify semantic support or real-world truth.
- **Scheduled scans:** the provided GitHub Actions workflow defaults to manual runs, with no persistent database across runs; do not rely on it for day-to-day change tracking without adding persistent storage.
