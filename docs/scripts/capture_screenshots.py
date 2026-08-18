"""Capture the README's product screenshots from the running app.

These images used to be captured by hand, and it showed: the four showcase files in
`docs/assets/` were 1280x720 *JPEGs* carrying a `.png` extension. Lossy compression on a
UI screenshot is the worst case for the format — every label in the product is small text
on a flat panel, which is exactly what JPEG's chroma subsampling and ringing destroy — and
1280px leaves nothing in reserve once GitHub scales the image down into its content
column on a high-DPI display.

So the capture is a script now, and it fixes both halves:

  * `device_scale_factor=2` renders a 1440x900 viewport into a 2880x1800 image, so there
    are real pixels behind every glyph after the browser scales it back down.
  * Playwright writes PNG, losslessly, and cannot be talked into writing a JPEG with the
    wrong extension.

Being a script also buys the thing hand-capture never had: when the UI changes, the
screenshots are one command behind it rather than however long it takes someone to
notice they are stale.

    pip install playwright            # once; no `playwright install` needed, see below
    api/.venv/Scripts/python docs/scripts/capture_screenshots.py

Playwright is deliberately not in `requirements-dev.txt`: that file is the test
dependencies CI installs on every run, and CI has no reason to carry a browser driver to
run pytest. This is a docs tool, installed by whoever is regenerating the images.

Both servers must already be up (`npm run dev --prefix web` and the uvicorn app on 8000),
because the point is to photograph the real product against the seeded records — not a
mock. The chat shot in particular runs a live agent turn, so it costs an OpenAI call and
its wording will differ run to run. That is the honest version of that screenshot; the
alternative is a picture of something the product never said.

Chrome is driven through Playwright's `channel="chrome"`, which reuses the browser already
installed on the machine instead of downloading Playwright's own ~130MB build.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSETS = REPO_ROOT / "docs" / "assets"

# The demo door's password is printed on the demo page itself; every account behind it is
# fictional. Keeping it here is not a leak, it is the same string a visitor reads.
DEMO_EMAIL = "alex.chen@pathpilot.example.edu"

# 1440x900 at 2x. The viewport is the design's desktop size — wide enough that the chat's
# audit rail is past its `lg:` breakpoint and actually renders, which is the whole subject
# of the first screenshot.
VIEWPORT = {"width": 1440, "height": 900}
SCALE = 2

# The question is the one the old screenshot asked, so the new image is a like-for-like
# replacement rather than a different claim about the product.
CHAT_QUESTION = "What should I take next term, and what would delay graduation?"


def settle(page: Page) -> None:
    """Wait until the view has its data and has stopped animating.

    `networkidle` alone is not enough: the shell renders `.state--loading` while its own
    fetches are in flight, and the design's panels slide in on a ~200ms transition. A
    screenshot taken in either window photographs the loading state.
    """
    page.wait_for_load_state("networkidle")
    page.wait_for_function("document.querySelectorAll('.state--loading').length === 0")
    page.wait_for_timeout(600)


def sign_in(page: Page, base: str) -> None:
    page.goto(f"{base}/demo")
    page.get_by_role("button", name="Alex Chen").click()
    page.wait_for_url(f"{base}/")
    settle(page)


def ask_in_chat(page: Page) -> None:
    """Run one real agent turn so the audit rail has something true in it."""
    page.fill("#chat-input", CHAT_QUESTION)
    page.press("#chat-input", "Enter")
    # The composer disables itself for the duration of the turn; re-enabling is the
    # signal that the answer and its audit entries have landed. A multi-tool turn is
    # slow — two minutes is generous rather than optimistic.
    page.wait_for_selector("#chat-input:not([disabled])", timeout=120_000)
    settle(page)
    # The transcript auto-scrolls to the newest thing in it, which for a turn that
    # proposes courses is the bottom of the suggestion stack — a screenshot taken there
    # opens mid-sentence. Scroll back so the question sits at the top of the pane and the
    # answer reads from its first word, which is what the shot is meant to show.
    page.evaluate(
        """() => {
            const pane = document.querySelector('.nx-scroll')
            const asked = [...pane.children].reverse()
                .find((el) => el.className.includes('justify-end'))
            if (!asked) return
            pane.scrollTop +=
                asked.getBoundingClientRect().top - pane.getBoundingClientRect().top - 16
        }"""
    )
    page.wait_for_timeout(300)


SHOTS = [
    {"file": "agent-tool-trace.png", "path": "/", "prepare": ask_in_chat},
    {"file": "degree-progress.png", "path": "/planner", "prepare": None},
    {"file": "registration-mission.png", "path": "/mission", "prepare": None},
    {"file": "course-sequence.png", "path": "/sequence", "prepare": None},
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://localhost:5173", help="running web app")
    parser.add_argument(
        "--only",
        action="append",
        help="capture just this file (repeatable); default is all four",
    )
    parser.add_argument(
        "--headed", action="store_true", help="show the browser instead of running headless"
    )
    args = parser.parse_args()

    wanted = [s for s in SHOTS if not args.only or s["file"] in args.only]
    if not wanted:
        print(f"no shot matches {args.only}; known: {[s['file'] for s in SHOTS]}", file=sys.stderr)
        return 2

    ASSETS.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=not args.headed)
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=SCALE)
        # Preferences are read from localStorage on first paint, so they have to be in
        # place before the app's own scripts run — set afterwards, the first frame is
        # drawn in the wrong theme and the screenshot can catch it. Light and English
        # match the images these replace.
        context.add_init_script(
            "localStorage.setItem('pp-theme', 'light');"
            "localStorage.setItem('pp-locale', 'en');"
        )
        page = context.new_page()

        try:
            sign_in(page, args.base)
        except PlaywrightTimeoutError:
            print(
                f"could not reach the demo door at {args.base}/demo — is the web dev server up?",
                file=sys.stderr,
            )
            return 1

        for shot in wanted:
            page.goto(f"{args.base}{shot['path']}")
            settle(page)
            if shot["prepare"]:
                shot["prepare"](page)
            out = ASSETS / shot["file"]
            page.screenshot(path=out, scale="device")
            size = out.stat().st_size // 1024
            print(f"  {shot['file']}  {VIEWPORT['width'] * SCALE}x{VIEWPORT['height'] * SCALE}  {size}KB")

        context.close()
        browser.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
