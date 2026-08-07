"""Generate transcript *photos* — the thing a student on a phone actually uploads.

    .venv/Scripts/python -m tests.fixtures.make_photos

Drawn as images rather than rendered from the PDF fixtures, for two reasons. Rendering a PDF
needs poppler or pymupdf, a system dependency this project has kept out; and drawing means
the degradation is a controlled variable rather than whatever the rasteriser happened to do.

**The ground truth is free.** These reproduce the same rows as `transcript_sis_export.pdf`,
so the labels in `eval/intake_cases.py` already describe them — an OCR reading can be scored
against the same expectations as the text-layer reading, and the only difference between the
two runs is the channel.

Three degradations, each chosen because it breaks recognition differently:

- `photo_clean`  — flat, sharp, well lit. The best case a phone produces, and the control:
                   if this one misreads, nothing about the pipeline is trustworthy.
- `photo_skewed` — rotated a few degrees with a shadow gradient across the page, which is
                   what a photo taken at a desk with an overhead light looks like.
- `photo_lowres` — downscaled and JPEG-crushed, the small-file case. This is where character
                   confusion lives: at low resolution `B`/`8` and `0`/`O` stop being
                   distinguishable by shape, and a transcript is made almost entirely of
                   those characters.

Nothing here is a real record. Same rule as the PDF fixtures — the layout came from a real
Albert export, the data did not.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent

WIDTH, HEIGHT = 1700, 2200
MARGIN = 120

# Same rows as transcript_sis_export.pdf, so one label set scores both channels.
LINES = [
    ("Unofficial", "small"),
    ("Name: Jordan Sample", "small"),
    ("Birthdate (MM/DD): 01/01", "small"),
    ("Print Date: 08/03/2026", "small"),
    ("Student ID: N00000001", "small"),
    ("Fictional University", "body"),
    ("Beginning of Graduate Record", "body"),
    ("", "body"),
    ("Fall 2024", "bold"),
    ("School of Professional Studies", "small"),
    ("Master of Science", "small"),
    ("Major: Management and Analytics", "small"),
    ("Quantitative Methods for Business Analysis MASY1-GC 1015-400 3.0 A-", "body"),
    ("Management Skills for Technology", "body"),
    ("Professionals MASY1-GC 1115-400 3.0 A-", "body"),
    ("AHRS EHRS QHRS QPTS GPA", "small"),
    ("Current 12.0 12.0 12.0 45.003 3.750", "small"),
    ("Cumulative 12.0 12.0 12.0 45.003 3.750", "small"),
    ("", "body"),
    ("Spring 2025", "bold"),
    ("School of Professional Studies", "small"),
    ("Master of Science", "small"),
    ("Major: Management and Analytics", "small"),
    ("Database Management MASY1-GC 1500-400 3.0 A", "body"),
    ("Managing Technical Projects MASY1-GC 1600-400 3.0 A-", "body"),
    ("AHRS EHRS QHRS QPTS GPA", "small"),
    ("Current 12.0 12.0 12.0 47.001 3.917", "small"),
    ("Cumulative 24.0 24.0 24.0 92.004 3.834", "small"),
    ("", "body"),
    ("Fall 2025", "bold"),
    ("School of Professional Studies", "small"),
    ("Master of Science", "small"),
    ("Major: Management and Analytics", "small"),
    ("Foundations of Business Informatics MASY1-GC 2400-400 3.0", "body"),
    ("AHRS EHRS QHRS QPTS GPA", "small"),
    ("Current 12.0 0.0 0.0 0.000 0.000", "small"),
    ("Cumulative 36.0 24.0 24.0 92.004 3.834", "small"),
    ("", "body"),
    ("End of Graduate Record", "body"),
]


def _fonts():
    """DejaVu ships with matplotlib/PIL on most installs; fall back to the bitmap default."""
    candidates = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibri.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return {
                "small": ImageFont.truetype(path, 30),
                "body": ImageFont.truetype(path, 34),
                "bold": ImageFont.truetype(path, 38),
            }
    default = ImageFont.load_default()
    return {"small": default, "body": default, "bold": default}


def _page() -> Image.Image:
    fonts = _fonts()
    image = Image.new("RGB", (WIDTH, HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    y = MARGIN
    for text, kind in LINES:
        if text:
            draw.text((MARGIN, y), text, fill=(15, 15, 20), font=fonts[kind])
        y += 48 if kind != "small" else 42
    return image


def build_clean() -> None:
    _page().save(HERE / "transcript_photo_clean.jpg", quality=92)


def build_skewed() -> None:
    """Rotated, with an overhead-light gradient — a photo taken at a desk."""
    page = _page().rotate(-2.4, expand=True, fillcolor="white", resample=Image.BICUBIC)

    # A soft diagonal shadow, brightest top-left, as a lamp behind the shoulder produces.
    shadow = Image.new("L", page.size, 0)
    shade = ImageDraw.Draw(shadow)
    for i in range(page.size[0]):
        shade.line([(i, 0), (i, page.size[1])], fill=int(40 * i / page.size[0]))
    shadow = shadow.filter(ImageFilter.GaussianBlur(60))
    page = Image.composite(Image.new("RGB", page.size, (150, 148, 145)), page, shadow)

    page.filter(ImageFilter.GaussianBlur(0.6)).save(
        HERE / "transcript_photo_skewed.jpg", quality=80
    )


def build_lowres() -> None:
    """Downscaled and JPEG-crushed: where B/8 and 0/O stop being different shapes."""
    page = _page()
    small = page.resize((page.width // 3, page.height // 3), Image.LANCZOS)
    small.save(HERE / "transcript_photo_lowres.jpg", quality=28)


def main() -> None:
    build_clean()
    build_skewed()
    build_lowres()
    for path in sorted(HERE.glob("transcript_photo_*.jpg")):
        print(f"  {path.name:34} {path.stat().st_size:>8,} bytes")


if __name__ == "__main__":
    main()
