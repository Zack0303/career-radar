"""Zero-dependency print-ready bilingual A4 HTML resume renderer."""

from __future__ import annotations

import html
from typing import Any, Mapping


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _extract_lang_payload(data: Mapping[str, Any], lang: str) -> Mapping[str, Any]:
    if lang in data and isinstance(data[lang], Mapping):
        return data[lang]
    if "name" in data and "sections" in data:
        return data
    raise ValueError(f"Resume payload missing language '{lang}' and top-level resume fields.")


def _require_fields(payload: Mapping[str, Any]) -> None:
    required = ("name", "title", "sections", "summary", "skills", "jobs", "projects", "education")
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"Resume payload missing required fields: {', '.join(missing)}")
    if len(payload["sections"]) < 5:
        raise ValueError("Resume 'sections' must contain at least 5 section headings.")


def render_resume_html(data: Mapping[str, Any], lang: str = "en") -> str:
    """Render a clean, restrained, print-ready A4 HTML resume in EN or CN."""
    payload = _extract_lang_payload(data, lang)
    _require_fields(payload)

    sections = [_esc(s) for s in payload["sections"]]
    is_cn = lang.lower().startswith("cn") or lang.lower().startswith("zh")
    html_lang = "zh-CN" if is_cn else "en"

    skills_rows = "\n".join(
        f"<tr><th>{_esc(label)}</th><td>{_esc(val)}</td></tr>"
        for label, val in payload["skills"]
    )

    jobs_blocks = []
    for job in payload["jobs"]:
        bullets = "\n".join(f"<li>{_esc(b)}</li>" for b in job.get("bullets", ()))
        jobs_blocks.append(
            "<div class='entry'>"
            f"<div class='entry-head'><h3>{_esc(job['company'])}</h3><span class='date'>{_esc(job.get('date', ''))}</span></div>"
            f"<div class='meta'>{_esc(job.get('role', ''))}</div>"
            f"<ul>{bullets}</ul>"
            "</div>"
        )
    jobs_html = "\n".join(jobs_blocks)

    project_blocks = []
    for proj in payload["projects"]:
        bullets = "\n".join(f"<li>{_esc(b)}</li>" for b in proj.get("bullets", ()))
        intro = f"<p class='proj-intro'>{_esc(proj['intro'])}</p>" if proj.get("intro") else ""
        project_blocks.append(
            "<div class='entry'>"
            f"<div class='entry-head'><h3>{_esc(proj['name'])}</h3><span class='date'>{_esc(proj.get('context', ''))}</span></div>"
            f"{intro}"
            f"<ul>{bullets}</ul>"
            "</div>"
        )
    projects_html = "\n".join(project_blocks)

    edu_blocks = []
    for edu in payload["education"]:
        detail = f"<div class='meta'>{_esc(edu['detail'])}</div>" if edu.get("detail") else ""
        edu_blocks.append(
            "<div class='edu-row'>"
            f"<span>{_esc(edu['degree'])}</span><span class='date'>{_esc(edu.get('date', ''))}</span>"
            "</div>"
            f"{detail}"
        )
    edu_html = "\n".join(edu_blocks)

    availability = (
        f"<div class='meta'>{_esc(payload['availability'])}</div>" if payload.get("availability") else ""
    )
    languages = f"<p class='meta lang-line'>{_esc(payload['languages'])}</p>" if payload.get("languages") else ""

    return f"""<!DOCTYPE html>
<html lang="{html_lang}">
<head>
  <meta charset="utf-8">
  <title>{_esc(payload['name'])} — {_esc(payload['title'])}</title>
  <style>
    @page {{
      size: A4;
      margin: 14mm 15mm;
    }}
    * {{
      box-sizing: border-box;
    }}
    body {{
      margin: 0 auto;
      max-width: 794px;
      padding: 28px 34px;
      font-family: "Inter", -apple-system, BlinkMacSystemFont, "PingFang SC", "Noto Sans SC", "Microsoft YaHei", sans-serif;
      font-size: 9.6pt;
      line-height: 1.5;
      color: #1F2937;
      background: #FFFFFF;
    }}
    header {{
      margin-bottom: 12px;
    }}
    h1 {{
      margin: 0;
      font-size: 21pt;
      font-weight: 700;
      color: #111827;
      letter-spacing: -0.01em;
    }}
    .headline {{
      margin: 2px 0 4px 0;
      font-size: 11pt;
      font-weight: 500;
      color: #374151;
    }}
    .meta {{
      font-size: 8.6pt;
      color: #6B7280;
    }}
    h2 {{
      margin: 14px 0 7px 0;
      padding-bottom: 3px;
      font-size: 10.5pt;
      font-weight: 700;
      color: #111827;
      border-bottom: 0.75px solid #D1D5DB;
    }}
    p {{
      margin: 0 0 6px 0;
    }}
    table.skills {{
      width: 100%;
      border-collapse: collapse;
    }}
    table.skills th {{
      width: 24%;
      text-align: left;
      vertical-align: top;
      padding: 2px 12px 4px 0;
      font-weight: 600;
      color: #111827;
    }}
    table.skills td {{
      padding: 2px 0 4px 0;
      color: #374151;
    }}
    .entry {{
      margin-bottom: 9px;
      break-inside: avoid;
    }}
    .entry-head, .edu-row {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
    }}
    .entry-head h3 {{
      margin: 0;
      font-size: 9.8pt;
      font-weight: 700;
      color: #111827;
    }}
    .date {{
      font-size: 8.5pt;
      color: #6B7280;
      white-space: nowrap;
    }}
    .proj-intro {{
      margin: 3px 0 4px 0;
      color: #374151;
    }}
    ul {{
      margin: 4px 0 0 0;
      padding-left: 16px;
    }}
    li {{
      margin-bottom: 2.5px;
    }}
    .edu-row {{
      margin-bottom: 3px;
    }}
    .lang-line {{
      margin-top: 6px;
    }}
    @media print {{
      body {{
        padding: 0;
        max-width: none;
      }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{_esc(payload['name'])}</h1>
    <div class="headline">{_esc(payload['title'])}</div>
    <div class="meta">{_esc(payload.get('contact', ''))}</div>
    {availability}
  </header>

  <section>
    <h2>{sections[0]}</h2>
    <p>{_esc(payload['summary'])}</p>
  </section>

  <section>
    <h2>{sections[1]}</h2>
    <table class="skills">
      {skills_rows}
    </table>
  </section>

  <section>
    <h2>{sections[2]}</h2>
    {jobs_html}
  </section>

  <section>
    <h2>{sections[3]}</h2>
    {projects_html}
  </section>

  <section>
    <h2>{sections[4]}</h2>
    {edu_html}
    {languages}
  </section>
</body>
</html>
"""
