"""Print the section index of the ingested corpus, for authoring eval labels by hand.

    .venv/Scripts/python -m scripts.corpus_index --slug graduate__professional-studies__academic-policies
    .venv/Scripts/python -m scripts.corpus_index --grep "withdraw|incomplete"
    .venv/Scripts/python -m scripts.corpus_index --pages

Labels must point at sections that exist. Writing them from memory of what a university
policy page probably says is how a golden set ends up measuring the author's assumptions.
"""

import argparse
import json
import re
from pathlib import Path

SECTIONS_DIR = Path(__file__).resolve().parent.parent / "data" / "sections"


def load() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(SECTIONS_DIR.glob("*.json"))]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", help="show all sections of one page")
    parser.add_argument("--grep", help="regex over heading paths, across the corpus")
    parser.add_argument("--text", help="regex over section text, across the corpus")
    parser.add_argument("--pages", action="store_true", help="list pages with section counts")
    parser.add_argument("--home-only", action="store_true", help="restrict to scope=home")
    args = parser.parse_args()

    pages = load()
    if args.home_only:
        pages = [p for p in pages if p["scope"] == "home"]

    if args.pages:
        for page in pages:
            print(f"  {len(page['sections']):>4}  {page['scope']:<11} {page['slug']}")
        print(f"\n{len(pages)} pages, {sum(len(p['sections']) for p in pages)} sections")
        return

    if args.slug:
        page = next((p for p in pages if p["slug"] == args.slug), None)
        if page is None:
            raise SystemExit(f"no page {args.slug!r}")
        print(f"{page['title']}  ({page['url']})\n")
        for s in page["sections"]:
            print(f"  [{len(s['text']):>5}c] {s['heading_path']}")
        return

    pattern = args.grep or args.text
    if not pattern:
        raise SystemExit("pass --slug, --grep, --text, or --pages")

    rx = re.compile(pattern, re.IGNORECASE)
    hits = 0
    for page in pages:
        for s in page["sections"]:
            target = s["heading_path"] if args.grep else s["text"]
            if rx.search(target):
                hits += 1
                print(f"\n  {page['slug']}")
                print(f"    {s['heading_path']}  ({len(s['text'])}c)")
                if args.text:
                    m = rx.search(s["text"])
                    start = max(m.start() - 70, 0)
                    print(f"    …{s['text'][start:m.end() + 90]}…".replace("\n", " "))
    print(f"\n{hits} matching sections")


if __name__ == "__main__":
    main()
