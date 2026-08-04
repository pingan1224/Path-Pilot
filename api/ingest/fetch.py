"""Stage 1 — fetch the seed pages into a local snapshot.

    .venv/Scripts/python -m ingest.fetch            # fetch anything not cached
    .venv/Scripts/python -m ingest.fetch --force    # re-fetch everything
    .venv/Scripts/python -m ingest.fetch --dry-run  # list what would be fetched

Raw HTML lands in data/raw/pages/ and a manifest records URL, status, byte count, SHA-256,
and fetch time. Two reasons the raw HTML is kept rather than parsed on the fly:

* Extraction is the stage most likely to be wrong. Keeping the bytes means a bad selector
  costs a re-parse, not another 34 requests against someone else's server.
* The eval labels reference this corpus. A snapshot with a recorded date makes the
  measurements reproducible even after the upstream pages change — which they will.

Politeness is not decoration here: a fixed delay between requests, an identifying
User-Agent with a contact address, and a hard stop on repeated failures.
"""

import argparse
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from ingest.sources import REQUEST_DELAY_SECONDS, SOURCES, USER_AGENT

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PAGES_DIR = DATA_DIR / "raw" / "pages"
MANIFEST = DATA_DIR / "raw" / "manifest.json"

# Stop rather than hammer a server that is clearly unhappy with us.
MAX_CONSECUTIVE_FAILURES = 3


def load_manifest() -> dict[str, dict]:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {}


def save_manifest(manifest: dict[str, dict]) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="re-fetch pages already cached")
    parser.add_argument("--dry-run", action="store_true", help="show the plan, fetch nothing")
    args = parser.parse_args()

    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()

    todo = [s for s in SOURCES if args.force or s.slug not in manifest]
    print(f"seed list: {len(SOURCES)} pages · cached: {len(manifest)} · to fetch: {len(todo)}")

    if args.dry_run:
        for s in todo:
            print(f"  {s.scope:10} {s.topic:12} {s.url}")
        return
    if not todo:
        print("nothing to do (use --force to re-fetch)")
        return

    consecutive_failures = 0
    fetched = 0
    changed = 0

    with httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        timeout=30.0,
        follow_redirects=True,
    ) as client:
        for i, source in enumerate(todo, 1):
            if i > 1:
                time.sleep(REQUEST_DELAY_SECONDS)

            try:
                response = client.get(source.url)
            except httpx.HTTPError as exc:
                consecutive_failures += 1
                print(f"  [{i}/{len(todo)}] FAIL {source.slug}: {type(exc).__name__}")
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    print("  stopping: too many consecutive failures")
                    break
                continue

            # A 202 with an empty body is how www.nyu.edu's CDN silently refuses bots.
            # Treat any empty 2xx as a refusal rather than recording an empty page.
            if response.status_code >= 400 or not response.content:
                consecutive_failures += 1
                print(
                    f"  [{i}/{len(todo)}] FAIL {source.slug}: "
                    f"HTTP {response.status_code}, {len(response.content)} bytes"
                )
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    print("  stopping: too many consecutive failures")
                    break
                continue

            consecutive_failures = 0
            html = response.text
            digest = hashlib.sha256(html.encode("utf-8")).hexdigest()
            previous = manifest.get(source.slug, {}).get("sha256")

            (PAGES_DIR / f"{source.slug}.html").write_text(html, encoding="utf-8")
            manifest[source.slug] = {
                "url": source.url,
                "school": source.school,
                "level": source.level,
                "topic": source.topic,
                "office": source.office,
                "scope": source.scope,
                "status": response.status_code,
                "bytes": len(html),
                "sha256": digest,
                "fetched_at": datetime.now(UTC).isoformat(),
            }
            fetched += 1
            if previous and previous != digest:
                changed += 1
                marker = "CHANGED"
            elif previous:
                marker = "same"
            else:
                marker = "new"
            print(f"  [{i}/{len(todo)}] ok   {source.slug}  {len(html):>7,}B  {marker}")

    save_manifest(manifest)
    print(f"\nfetched {fetched}/{len(todo)} · content changed on {changed} · manifest: {MANIFEST}")

    missing = [s.slug for s in SOURCES if s.slug not in manifest]
    if missing:
        print(f"still missing {len(missing)}: {', '.join(missing[:5])}{' ...' if len(missing) > 5 else ''}")


if __name__ == "__main__":
    main()
