"""Optional ReportLab A4 bilingual PDF resume exporter."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import xml.sax.saxutils as xml_utils

from career_radar.resume.renderer import _extract_lang_payload, _require_fields

_CJK_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
)


def _find_cjk_font() -> str:
    for candidate in _CJK_FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    raise RuntimeError(
        "No CJK system font found for Chinese PDF export. "
        "Use '--format html' or install Noto Sans CJK."
    )


def render_resume_pdf(
    data: Mapping[str, Any],
    out_path: Path,
    lang: str = "en",
) -> Path:
    """Render a clean A4 bilingual PDF resume using optional ReportLab."""
    try:
        from reportlab.lib.colors import HexColor
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import (
            KeepTogether,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as exc:
        raise RuntimeError(
            "ReportLab is required for PDF export. Install via 'pip install \"career-radar[pdf]\"' "
            "or use '--format html' (zero dependencies)."
        ) from exc

    payload = _extract_lang_payload(data, lang)
    _require_fields(payload)

    is_cn = lang.lower().startswith("cn") or lang.lower().startswith("zh")
    font_name = "Helvetica"
    bold_name = "Helvetica-Bold"
    if is_cn:
        cjk_path = _find_cjk_font()
        cjk_key = "CareerRadarCJK"
        if cjk_key not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(cjk_key, cjk_path))
        font_name = cjk_key
        bold_name = cjk_key

    def esc(val: Any) -> str:
        return xml_utils.escape(str(val or ""))

    body = ParagraphStyle(
        "body",
        fontName=font_name,
        fontSize=9.8 if is_cn else 9.2,
        leading=14.5 if is_cn else 12.2,
        textColor=HexColor("#1F2937"),
        wordWrap="CJK" if is_cn else None,
    )
    styles = {
        "body": body,
        "name": ParagraphStyle("name", parent=body, fontName=bold_name, fontSize=20, leading=24, textColor=HexColor("#111827")),
        "title": ParagraphStyle("title", parent=body, fontSize=11, leading=16, textColor=HexColor("#374151")),
        "meta": ParagraphStyle("meta", parent=body, fontSize=8.5, leading=11.5, textColor=HexColor("#6B7280")),
        "section": ParagraphStyle("section", parent=body, fontName=bold_name, fontSize=10.5, leading=14, spaceBefore=10, spaceAfter=6, textColor=HexColor("#111827")),
        "heading": ParagraphStyle("heading", parent=body, fontName=bold_name, fontSize=9.8, leading=13.5, textColor=HexColor("#111827")),
        "date": ParagraphStyle("date", parent=body, fontSize=8.5, leading=13.5, alignment=2, textColor=HexColor("#6B7280")),
        "bullet": ParagraphStyle("bullet", parent=body, leftIndent=11, bulletIndent=0, bulletFontName=font_name, bulletFontSize=8, spaceAfter=2.5),
    }

    class SectionParagraph(Paragraph):
        def draw(self) -> None:
            super().draw()
            self.canv.setStrokeColor(HexColor("#D1D5DB"))
            self.canv.setLineWidth(0.5)
            self.canv.line(0, -3, self.width, -3)

    content_width = A4[0] - 86

    def dated_row(left: str, right: str, style_key: str = "heading") -> Table:
        row = Table(
            [[Paragraph(esc(left), styles[style_key]), Paragraph(esc(right), styles["date"])]],
            colWidths=[content_width - 110, 110],
            hAlign="LEFT",
        )
        row.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        return row

    sections = list(payload["sections"])
    story: list[Any] = [
        Paragraph(esc(payload["name"]), styles["name"]),
        Paragraph(esc(payload["title"]), styles["title"]),
    ]
    if payload.get("contact"):
        story.append(Paragraph(esc(payload["contact"]), styles["meta"]))
    if payload.get("availability"):
        story.append(Paragraph(esc(payload["availability"]), styles["meta"]))

    story.append(SectionParagraph(esc(sections[0]), styles["section"]))
    story.append(Paragraph(esc(payload["summary"]), styles["body"]))

    story.append(SectionParagraph(esc(sections[1]), styles["section"]))
    skill_rows = [
        [Paragraph(esc(lbl), styles["heading"]), Paragraph(esc(val), styles["body"])]
        for lbl, val in payload["skills"]
    ]
    if skill_rows:
        sk_table = Table(skill_rows, colWidths=[120, content_width - 120], hAlign="LEFT")
        sk_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (0, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 1),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(sk_table)

    story.append(SectionParagraph(esc(sections[2]), styles["section"]))
    for job in payload["jobs"]:
        block = [
            dated_row(str(job["company"]), str(job.get("date", ""))),
            Paragraph(esc(job.get("role", "")), styles["meta"]),
        ]
        story.append(KeepTogether(block))
        for bullet in job.get("bullets", ()):
            story.append(Paragraph(esc(bullet), styles["bullet"], bulletText="•"))
        story.append(Spacer(1, 4))

    story.append(SectionParagraph(esc(sections[3]), styles["section"]))
    for proj in payload["projects"]:
        header_items = [dated_row(str(proj["name"]), str(proj.get("context", "")))]
        if proj.get("intro"):
            header_items.append(Paragraph(esc(proj["intro"]), styles["body"]))
        story.append(KeepTogether(header_items))
        for bullet in proj.get("bullets", ()):
            story.append(Paragraph(esc(bullet), styles["bullet"], bulletText="•"))
        story.append(Spacer(1, 4))

    story.append(SectionParagraph(esc(sections[4]), styles["section"]))
    for edu in payload["education"]:
        story.append(dated_row(str(edu["degree"]), str(edu.get("date", "")), style_key="body"))
        if edu.get("detail"):
            story.append(Paragraph(esc(edu["detail"]), styles["meta"]))
    if payload.get("languages"):
        story.append(Spacer(1, 5))
        story.append(Paragraph(esc(payload["languages"]), styles["meta"]))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        rightMargin=43,
        leftMargin=43,
        topMargin=32,
        bottomMargin=32,
        title=f"{payload['name']} - {payload['title']}",
    )

    def _footer(canvas: Any, pdf_doc: Any) -> None:
        canvas.setFont(font_name, 8)
        canvas.setFillColor(HexColor("#808080"))
        canvas.drawRightString(A4[0] - 43, 20, str(pdf_doc.page))

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return out_path
