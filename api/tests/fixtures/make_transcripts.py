"""Generate synthetic transcript PDFs for parser tests and the extraction eval.

    .venv/Scripts/python -m tests.fixtures.make_transcripts

**Every fixture here is invented.** No real NYU transcript has been seen, used, or
approximated from a real document — the course codes come from the public bulletin catalog
this project already ingested, and the names, grades, and layouts are made up. That is the
same rule the demo students follow, and it matters more here: a transcript is the most
sensitive document this product will ever touch, so the test corpus must not contain one.

Three layouts, chosen because they fail differently rather than to pad the count:

- `table`     — ruled columns, the shape a student information system exports
- `labelled`  — "Course: X / Grade: Y" prose lines, the shape of an advising letter
- `twocolumn` — two terms side by side, which is where naive line-based parsing breaks,
                because a single extracted line contains two unrelated courses

`messy` adds the cases that decide whether the parser is honest: a course code that is not
in the catalog, a grade the scale does not contain, an in-progress row with no grade at all,
and a line that is genuinely unreadable.
"""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

HERE = Path(__file__).resolve().parent

# Real catalog codes (from the ingested public bulletin), invented grades.
TABLE_ROWS = [
    ("Fall 2024", "MASY1-GC 1015", "Quantitative Methods for Business Analysis", "3.0", "A"),
    ("Fall 2024", "MASY1-GC 1115", "Management Skills for Technology Professionals", "3.0", "A-"),
    ("Spring 2025", "MASY1-GC 1500", "Database Management", "3.0", "B+"),
    ("Spring 2025", "MASY1-GC 1600", "Managing Technical Projects", "3.0", "A"),
    ("Fall 2025", "MASY1-GC 2400", "Foundations of Business Informatics", "3.0", "A-"),
]


def _doc(name: str):
    return SimpleDocTemplate(
        str(HERE / name),
        pagesize=LETTER,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title=name,
    )


def build_table() -> None:
    styles = getSampleStyleSheet()
    story = [
        Paragraph("FICTIONAL UNIVERSITY — UNOFFICIAL ACADEMIC RECORD", styles["Title"]),
        Paragraph(
            "Student: Jordan Sample &nbsp;&nbsp; ID: N00000001 &nbsp;&nbsp; "
            "Program: Management and Analytics (MS)",
            styles["Normal"],
        ),
        Spacer(1, 0.25 * inch),
    ]
    data = [["Term", "Course", "Title", "Cr", "Grade"], *TABLE_ROWS]
    table = Table(data, colWidths=[1.0 * inch, 1.2 * inch, 2.9 * inch, 0.4 * inch, 0.6 * inch])
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story += [table, Spacer(1, 0.2 * inch),
              Paragraph("Cumulative GPA: 3.72 &nbsp;&nbsp; Credits earned: 15.0", styles["Normal"])]
    _doc("transcript_table.pdf").build(story)


def build_labelled() -> None:
    styles = getSampleStyleSheet()
    story = [
        Paragraph("Advising Summary (unofficial)", styles["Title"]),
        Paragraph("Prepared for: Jordan Sample", styles["Normal"]),
        Spacer(1, 0.2 * inch),
    ]
    for term, code, title, credits, grade in TABLE_ROWS:
        story.append(
            Paragraph(
                f"Course: {code} — {title}<br/>"
                f"Term: {term} &nbsp; Credits: {credits} &nbsp; Grade: {grade}",
                styles["Normal"],
            )
        )
        story.append(Spacer(1, 0.12 * inch))
    _doc("transcript_labelled.pdf").build(story)


def build_twocolumn() -> None:
    """Two terms side by side — one extracted line holds two unrelated courses."""
    styles = getSampleStyleSheet()
    left = [("MASY1-GC 1015", "A"), ("MASY1-GC 1115", "A-")]
    right = [("MASY1-GC 1500", "B+"), ("MASY1-GC 1600", "A")]
    data = [["Fall 2024", "", "Spring 2025", ""]]
    for (lc, lg), (rc, rg) in zip(left, right, strict=True):
        data.append([lc, lg, rc, rg])
    table = Table(data, colWidths=[1.6 * inch, 0.6 * inch, 1.6 * inch, 0.6 * inch])
    table.setStyle(
        TableStyle(
            [("FONTSIZE", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
        )
    )
    _doc("transcript_twocolumn.pdf").build(
        [Paragraph("Record by Term (unofficial)", styles["Title"]), Spacer(1, 0.2 * inch), table]
    )


def build_messy() -> None:
    """The rows that decide whether the parser is honest rather than confident."""
    styles = getSampleStyleSheet()
    rows = [
        # In the catalog, clean grade -> should match.
        ("Fall 2024", "MASY1-GC 1015", "3.0", "A"),
        # Not in this program's catalog (a real possibility: cross-school elective).
        ("Fall 2024", "MKTG-GB 2350", "3.0", "B"),
        # Grade the scale does not contain.
        ("Spring 2025", "MASY1-GC 1500", "3.0", "S"),
        # In progress: no grade at all. Must not become a failing grade.
        ("Fall 2026", "MASY1-GC 2500", "3.0", ""),
        # Transfer credit with no course code at all.
        ("Transfer", "", "3.0", "TR"),
    ]
    data = [["Term", "Course", "Cr", "Grade"], *rows]
    table = Table(data, colWidths=[1.1 * inch, 1.4 * inch, 0.5 * inch, 0.7 * inch])
    table.setStyle(
        TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 8.5)])
    )
    _doc("transcript_messy.pdf").build(
        [
            Paragraph("Unofficial Record — Mixed Cases", styles["Title"]),
            Spacer(1, 0.2 * inch),
            table,
            Spacer(1, 0.2 * inch),
            Paragraph("~~~ scanned artifact: c0urse c0de illegible ~~~", styles["Normal"]),
        ]
    )


def build_no_text_layer() -> None:
    """A page with no extractable text — stands in for a scanned transcript.

    Drawn as vector lines rather than glyphs, so `extract_text()` legitimately returns
    nothing. This is the fixture that proves the "we cannot read this" path, which matters
    because a scan is the most likely thing a student actually uploads.
    """
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(HERE / "transcript_scanned.pdf"), pagesize=LETTER)
    for i in range(14):
        y = 720 - i * 28
        c.line(90, y, 520 - (i % 4) * 30, y)
    c.showPage()
    c.save()


def main() -> None:
    build_table()
    build_labelled()
    build_twocolumn()
    build_messy()
    build_no_text_layer()
    for path in sorted(HERE.glob("transcript_*.pdf")):
        print(f"  {path.name:32} {path.stat().st_size:>7,} bytes")


if __name__ == "__main__":
    main()
