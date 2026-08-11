"""Stage 7 — import the school's program list, so a student can say which one is theirs.

    .venv/Scripts/python -m ingest.programs --dry-run   # parse and report, touch nothing
    .venv/Scripts/python -m ingest.programs             # write Program rows

Reads the already-ingested school overview page and writes one `source='catalog'` Program
per degree listed on it. These are **listed, not encoded**: the page names the programs and
nothing else, so each row gets a name, a degree, a level, and its provenance, and a null
`total_credits_required` because the total genuinely is not known for it.

That null is the point of the whole stage. Before this, the only selectable program was the
one whose requirements had been hand-encoded, so "which program are you in?" had one
answer and every user got that answer whether or not it was true. Listing the real ones
lets a student say something true about themselves, and `services.profile.ENCODED_PROGRAMS`
stays the separate, smaller claim about which of them this tool can actually audit.

**The codes here are ours, not the university's.** The bulletin's program list is prose —
it publishes names, not identifiers — so the code is derived from the name (initials plus
degree) purely as a stable primary key. `name` and `catalog_url` are the real facts; the
code is an internal handle and is never shown to a student. Derivation is deterministic so
re-running this stage cannot renumber anyone's program out from under them, and a collision
is an error rather than a silent overwrite.

Undergraduate programs are deliberately absent: the undergraduate overview page is not in
the corpus (only four undergraduate policy pages are), so there is nothing to read them
from. Adding them is corpus work, not parser work.
"""

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.models import Program

SECTIONS_DIR = Path(__file__).resolve().parent.parent / "data" / "sections"

# The school overview page, and the heading whose body is the program list.
PAGE_SLUG = "graduate__professional-studies"
LIST_HEADING = "School of Professional Studies > Programs"

SCHOOL = "School of Professional Studies"
LEVEL = "graduate"

# "- Global Affairs (MS)" → name, degree. The bulletin writes every entry this way; a line
# that does not match is reported rather than skipped, because a silently dropped program is
# a student who cannot find themselves in the list.
ENTRY = re.compile(r"^-\s*(?P<name>.+?)\s*\((?P<degree>[A-Za-z/]+)\)\s*$")

# Words that carry no identifying weight in an initialism.
SKIP_WORDS = {"and", "of", "the", "for", "in"}


@dataclass(frozen=True)
class ParsedProgram:
    name: str
    degree: str
    code: str


def _initials(name: str) -> str:
    """Initials of the significant words, e.g. "Global Affairs" → "GA"."""
    words = re.split(r"[\s/,\-]+", name)
    letters = [w[0].upper() for w in words if w and w.lower() not in SKIP_WORDS]
    return "".join(letters)


def _derive_code(name: str, degree: str, taken: set[str]) -> str:
    """A short stable key. `programs.code` is VARCHAR(24), so the full name will not fit.

    Deterministic given the same list, and collisions get a numeric suffix rather than
    overwriting — two programs sharing a key would silently merge two degrees into one.
    """
    stem = _initials(name)[:16] or "PROG"
    degree_part = degree.replace("/", "").upper()[:6]
    base = f"{stem}-{degree_part}"[:24]
    if base not in taken:
        return base
    for n in range(2, 100):
        suffix = f"-{n}"
        candidate = f"{base[: 24 - len(suffix)]}{suffix}"
        if candidate not in taken:
            return candidate
    raise ValueError(f"cannot derive a unique code for {name!r}")


def page_provenance() -> tuple[str, datetime]:
    page = json.loads((SECTIONS_DIR / f"{PAGE_SLUG}.json").read_text(encoding="utf-8"))
    return page["url"], datetime.fromisoformat(page["fetched_at"])


def parse() -> tuple[list[ParsedProgram], list[str]]:
    """Returns (programs, unparsed lines). Unparsed lines are reported, never dropped."""
    page = json.loads((SECTIONS_DIR / f"{PAGE_SLUG}.json").read_text(encoding="utf-8"))
    section = next(
        (s for s in page["sections"] if s.get("heading_path") == LIST_HEADING), None
    )
    if section is None:
        raise SystemExit(
            f"No section {LIST_HEADING!r} in {PAGE_SLUG}.json. The overview page changed "
            "shape; re-check it before trusting anything this writes."
        )

    programs: list[ParsedProgram] = []
    problems: list[str] = []
    taken: set[str] = set()
    for line in section["text"].splitlines():
        line = line.strip()
        if not line:
            continue
        match = ENTRY.match(line)
        if match is None:
            problems.append(line)
            continue
        name = " ".join(match.group("name").split())
        degree = match.group("degree").upper()
        code = _derive_code(name, degree, taken)
        taken.add(code)
        programs.append(ParsedProgram(name=name, degree=degree, code=code))

    return programs, problems


def write(session, programs: list[ParsedProgram]) -> tuple[int, int, int]:
    """Returns (created, updated, already_encoded).

    Matching is by **name**, not by the derived code. An encoded program was written by
    ingest.requirements under its own code (MASY-MS-REAL) and appears on this list under
    the same name — matching on the code would create a second row for one real degree,
    and a student picking the wrong one of the pair would get "not supported" for a program
    this tool fully supports.

    An already-encoded row keeps its code, its credit total and its catalog_url: that URL
    points at the program's own requirements page, which is a better source than the
    overview list this stage reads.
    """
    url, verified_at = page_provenance()

    existing_by_name = {
        row.name.strip().lower(): row
        for row in session.scalars(select(Program).where(Program.source == "catalog"))
    }

    created = updated = encoded = 0
    for parsed in programs:
        program = existing_by_name.get(parsed.name.strip().lower())
        if program is not None:
            # Present already. Fill in only what this page is authoritative about.
            program.level = LEVEL
            program.school = SCHOOL
            if program.total_credits_required is not None:
                encoded += 1
            else:
                updated += 1
            continue

        program = Program(code=parsed.code)
        session.add(program)
        created += 1
        program.name = parsed.name
        program.degree = parsed.degree
        program.school = SCHOOL
        program.level = LEVEL
        program.source = "catalog"
        program.catalog_url = url
        program.catalog_verified_at = verified_at
        # total_credits_required stays null: this page names the program and says nothing
        # about what it requires. A number here would be invented.

    session.commit()
    return created, updated, encoded


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    programs, problems = parse()
    print(f"parsed {len(programs)} programs from {LIST_HEADING!r}")
    for parsed in programs:
        print(f"  {parsed.code:<24} {parsed.degree:<6} {parsed.name}")

    if problems:
        print(f"\n{len(problems)} line(s) did not parse — nothing was skipped silently:")
        for line in problems:
            print(f"  ! {line!r}")

    if args.dry_run:
        print("\ndry run — nothing written")
        return

    with get_sessionmaker()() as session:
        created, updated, encoded = write(session, programs)
    print(
        f"\nwrote {created} new, {updated} updated, "
        f"{encoded} already encoded and left alone"
    )


if __name__ == "__main__":
    main()
