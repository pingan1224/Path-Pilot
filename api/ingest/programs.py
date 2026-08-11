"""Stage 7 — import the school's programs, so a student can say which one is theirs.

    .venv/Scripts/python -m ingest.programs --dry-run   # parse and report, touch nothing
    .venv/Scripts/python -m ingest.programs             # write Program rows

Writes one `source='catalog'` Program per ingested degree page. These are **listed, not
encoded**: the page states what the degree requires in prose and tables, nobody has
transcribed it into rules, so each row gets a name, a degree, a level and its own URL, and
a null `total_credits_required`.

That null is the point of the whole stage. Before this, the only selectable program was the
one whose requirements had been hand-encoded, so "which program are you in?" had one
answer and every user got that answer whether or not it was true. Listing the real ones
lets a student say something true about themselves, and `services.profile.ENCODED_PROGRAMS`
stays the separate, smaller claim about which of them this tool can actually audit. The
null is also load-bearing downstream: `planning.loader` refuses to build a plan without a
credit total rather than reporting everyone as needing zero.

**Each program is read from its own page, not from the overview list.** The overview page
names all 23 and is how they were found, but a program's own page carries its title, its
URL, and — once someone transcribes it — its requirements. Reading the list instead would
give every program the same catalog_url, which is the overview page for all of them and the
right citation for none of them. The overview list is still parsed, as a cross-check: a
program named there with no ingested page is reported rather than silently missing.

**The codes here are ours, not the university's.** The bulletin publishes names, not
identifiers, so the code is derived from the name (initials plus degree) purely as a stable
primary key. `name` and `catalog_url` are the real facts; the code is an internal handle
and is never shown to a student. Derivation is deterministic so re-running this stage
cannot renumber anyone's program out from under them, and a collision is an error rather
than a silent overwrite.

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

# The school overview page, and the heading whose body is the program list. Used only to
# cross-check that every program named there has a page of its own.
PAGE_SLUG = "graduate__professional-studies"
LIST_HEADING = "School of Professional Studies > Programs"

# Each degree's own ingested page.
PROGRAM_SLUG_GLOB = "graduate__professional-studies__programs__*.json"

SCHOOL = "School of Professional Studies"
LEVEL = "graduate"

# "- Global Affairs (MS)" on the overview list, or "Global Affairs (MS)" as a page title.
# A line that does not match is reported rather than skipped, because a silently dropped
# program is a student who cannot find themselves in the list.
ENTRY = re.compile(r"^-?\s*(?P<name>.+?)\s*\((?P<degree>[A-Za-z/]+)\)\s*$")

# Words that carry no identifying weight in an initialism.
SKIP_WORDS = {"and", "of", "the", "for", "in"}


@dataclass(frozen=True)
class ParsedProgram:
    name: str
    degree: str
    code: str
    # The program's own bulletin page — the citation a student would be sent to.
    url: str
    verified_at: datetime


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


def _listed_on_overview() -> set[str]:
    """Program names the school overview page advertises, for cross-checking coverage."""
    path = SECTIONS_DIR / f"{PAGE_SLUG}.json"
    if not path.exists():
        return set()
    page = json.loads(path.read_text(encoding="utf-8"))
    section = next(
        (s for s in page["sections"] if s.get("heading_path") == LIST_HEADING), None
    )
    if section is None:
        return set()

    names = set()
    for line in section["text"].splitlines():
        line = line.strip()
        if not line.startswith("-"):
            continue
        match = ENTRY.match(line)
        if match:
            names.add(" ".join(match.group("name").split()))
    return names


def parse() -> tuple[list[ParsedProgram], list[str]]:
    """Read one program per ingested degree page.

    Returns (programs, problems). Problems are reported, never swallowed: a page whose
    title does not parse and a program advertised on the overview with no page of its own
    are both students who cannot find themselves in the picker.
    """
    programs: list[ParsedProgram] = []
    problems: list[str] = []
    taken: set[str] = set()

    for path in sorted(SECTIONS_DIR.glob(PROGRAM_SLUG_GLOB)):
        page = json.loads(path.read_text(encoding="utf-8"))
        title = " ".join((page.get("title") or "").split())
        match = ENTRY.match(title)
        if match is None:
            problems.append(f"{path.stem}: title {title!r} is not '<name> (<degree>)'")
            continue

        name = " ".join(match.group("name").split())
        degree = match.group("degree").upper()
        code = _derive_code(name, degree, taken)
        taken.add(code)
        programs.append(
            ParsedProgram(
                name=name,
                degree=degree,
                code=code,
                url=page["url"],
                verified_at=datetime.fromisoformat(page["fetched_at"]),
            )
        )

    # Coverage check against what the school says it offers. A program on the overview with
    # no ingested page is a gap in the corpus, and the picker would simply not show it —
    # which looks exactly like the school not offering it.
    advertised = _listed_on_overview()
    found = {p.name for p in programs}
    for missing in sorted(advertised - found):
        problems.append(f"listed on the overview but no ingested page: {missing!r}")

    return programs, problems


def write(session, programs: list[ParsedProgram]) -> tuple[int, int, int]:
    """Returns (created, updated, already_encoded).

    Matching is by **name**, not by the derived code. An encoded program was written by
    ingest.requirements under its own code (MASY-MS-REAL) and appears on this list under
    the same name — matching on the code would create a second row for one real degree,
    and a student picking the wrong one of the pair would get "not supported" for a program
    this tool fully supports.

    An already-encoded row keeps its code and its credit total, both of which come from
    ingest.requirements and are more than this stage knows.
    """
    existing_by_name = {
        row.name.strip().lower(): row
        for row in session.scalars(select(Program).where(Program.source == "catalog"))
    }

    created = updated = encoded = 0
    for parsed in programs:
        program = existing_by_name.get(parsed.name.strip().lower())
        if program is None:
            program = Program(code=parsed.code)
            session.add(program)
            created += 1
            program.name = parsed.name
            program.degree = parsed.degree
            program.source = "catalog"
        elif program.total_credits_required is not None:
            encoded += 1
        else:
            updated += 1

        program.school = SCHOOL
        program.level = LEVEL
        # Every row gets its own page, including ones written by an earlier run of this
        # stage that had only the overview list to cite. Encoded programs already point at
        # their own page; this rewrites it to the same value.
        program.catalog_url = parsed.url
        program.catalog_verified_at = parsed.verified_at
        # total_credits_required is deliberately not set. The page states a credit total in
        # prose, but that number's job here is to say whether anyone has transcribed the
        # requirements — planning.loader treats null as "not encoded" and refuses. Filling
        # it from the page would announce a program as auditable while its rules are still
        # unwritten.

    session.commit()
    return created, updated, encoded


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    programs, problems = parse()
    print(f"parsed {len(programs)} programs from their own ingested pages")
    for parsed in programs:
        print(f"  {parsed.code:<24} {parsed.degree:<6} {parsed.name}")

    if problems:
        print(f"\n{len(problems)} problem(s) — nothing was skipped silently:")
        for line in problems:
            print(f"  ! {line}")

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
