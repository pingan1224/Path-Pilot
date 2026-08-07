"""Generate synthetic transcript PDFs for parser tests and the extraction eval.

    .venv/Scripts/python -m tests.fixtures.make_transcripts

**Every fixture here is invented.** No real NYU transcript has been seen, used, or
approximated from a real document — the course codes come from the public bulletin catalog
this project already ingested, and the names, grades, and layouts are made up. That is the
same rule the demo students follow, and it matters more here: a transcript is the most
sensitive document this product will ever touch, so the test corpus must not contain one.

Four layouts, chosen because they fail differently rather than to pad the count:

- `table`      — ruled columns, the shape a student information system exports
- `labelled`   — "Course: X / Grade: Y" prose lines, the shape of an advising letter
- `twocolumn`  — two terms side by side, which is where naive line-based parsing breaks,
                 because a single extracted line contains two unrelated courses
- `sis_export` — the shape a real Albert export has: the whole row on one line with the
                 title first, a section suffix on the code, wrapped titles, and a per-term
                 GPA summary block that looks like a course row to a careless parser

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


def build_sis_export() -> None:
    """The shape a real Albert unofficial-transcript export actually has.

    Added 2026-08-07 after the reader met its first real transcript. The other four layouts
    were reasoned from how PDFs extract; this one is drawn from a genuine NYU SPS export,
    and it differs from all of them in four ways that each break a different assumption:

    - **The whole row is one extracted line**, title first: `Database Management
      MASY1-GC 1500-400 3.0 A-`. The `table` fixture emits one cell per line, so a parser
      tuned only on that has never seen the fields arrive together.
    - **The course code carries a section suffix** (`-400`) that is not part of the code.
    - **Long titles wrap**, putting the code on a line of its own with its title stranded
      one or two lines above it.
    - **Each term ends with a GPA summary block** — `Current 12.0 12.0 12.0 45.003 3.750` —
      six numbers on a line, sitting exactly where a credits-and-grade parser is looking.
      This is the row most likely to be read as a course.

    Everything identifying is invented, as everywhere else here: the real document that
    prompted this fixture carried a name, a birthdate, and a student number, and was never
    copied into this repository. What was copied is the shape.
    """
    styles = getSampleStyleSheet()
    story = [
        Paragraph("Unofficial", styles["Normal"]),
        Paragraph(
            "Name: Jordan Sample<br/>Birthdate (MM/DD): 01/01<br/>"
            "Print Date: 08/03/2026<br/>Student ID: N00000001",
            styles["Normal"],
        ),
        Paragraph("Fictional University", styles["Normal"]),
        Paragraph("Beginning of Graduate Record", styles["Normal"]),
        Spacer(1, 0.12 * inch),
    ]

    terms = [
        (
            "Fall 2024",
            [
                ("Quantitative Methods for Business Analysis", "MASY1-GC 1015-400", "3.0", "A-"),
                # Long enough to wrap, stranding the code on its own line.
                ("Management Skills for Technology Professionals", "MASY1-GC 1115-400", "3.0", "A-"),
            ],
            "12.0 12.0 12.0 45.003 3.750",
            "12.0 12.0 12.0 45.003 3.750",
        ),
        (
            "Spring 2025",
            [
                ("Database Management", "MASY1-GC 1500-400", "3.0", "A"),
                ("Managing Technical Projects", "MASY1-GC 1600-400", "3.0", "A-"),
            ],
            "12.0 12.0 12.0 47.001 3.917",
            "24.0 24.0 24.0 92.004 3.834",
        ),
        (
            # In progress: credits enrolled, nothing earned, no grade column at all.
            "Fall 2025",
            [("Foundations of Business Informatics", "MASY1-GC 2400-400", "3.0", "")],
            "12.0 0.0 0.0 0.000 0.000",
            "36.0 24.0 24.0 92.004 3.834",
        ),
    ]

    for term, rows, current, cumulative in terms:
        story += [
            Paragraph(term, styles["Normal"]),
            Paragraph("School of Professional Studies", styles["Normal"]),
            Paragraph("Master of Science", styles["Normal"]),
            Paragraph("Major: Management and Analytics", styles["Normal"]),
        ]
        for title, code, credits, grade in rows:
            story.append(Paragraph(f"{title} {code} {credits} {grade}".rstrip(), styles["Normal"]))
        story += [
            Paragraph("AHRS EHRS QHRS QPTS GPA", styles["Normal"]),
            Paragraph(f"Current {current}", styles["Normal"]),
            Paragraph(f"Cumulative {cumulative}", styles["Normal"]),
            Spacer(1, 0.1 * inch),
        ]

    story.append(Paragraph("End of Graduate Record", styles["Normal"]))
    _doc("transcript_sis_export.pdf").build(story)


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
    build_sis_export()
    build_no_text_layer()
    for path in sorted(HERE.glob("transcript_*.pdf")):
        print(f"  {path.name:32} {path.stat().st_size:>7,} bytes")


if __name__ == "__main__":
    main()
