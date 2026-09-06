"""Capture the README screenshots from a running instance of the app.

Committing screenshots without a way to regenerate them means they rot the moment the
interface changes. This script re-shoots them against whatever instance you point it at,
so refreshing the README after a UI change is one command rather than a manual session
with a cropping tool.

    python scripts/capture_screenshots.py                       # the live deployment
    python scripts/capture_screenshots.py --url http://localhost:8501

Requires playwright, which is a documentation-only dependency:

    pip install playwright && playwright install chromium
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import PROJECT_ROOT  # noqa: E402
from src.logging_conf import get_logger  # noqa: E402

log = get_logger(__name__)

IMAGE_DIR = PROJECT_ROOT / "docs" / "images"
LIVE_URL = "https://enterprise-ai-assistant-rag.streamlit.app/"

# A wide, tall viewport: the landing view is meant to be read in one go, and the trace
# panel is long when the agent self-corrects.
VIEWPORT = {"width": 1440, "height": 1000}

# The question that shows the agent's most distinctive behaviour. The corpus cannot
# answer it, so the graph rewrites its query twice and then declines.
SELF_CORRECTION_QUESTION = "What is ACME's policy on cryptocurrency payments from customers?"
SIMPLE_QUESTION = "How many API requests per minute does the Growth plan allow?"


def _wait_for_app(page, timeout: int = 180_000) -> None:
    """Wait until Streamlit has rendered the app, not merely served the HTML shell.

    Waits on the chat input rather than the custom hero markup: the input is a native
    Streamlit element with a stable test id, whereas custom HTML can be injected before
    the rest of the page settles.
    """
    page.wait_for_selector('[data-testid="stChatInput"]', timeout=timeout)
    page.wait_for_selector(".hero", timeout=timeout)
    page.wait_for_timeout(3_000)


def _ask(page, question: str, settle_ms: int = 45_000) -> None:
    """Type a question into the chat input and wait for the answer to land."""
    box = page.get_by_placeholder("Ask about ACME's documentation…")
    box.click()
    box.fill(question)
    box.press("Enter")

    # The turn is done once a trace exists. `state="attached"` rather than the default
    # "visible": the trace lives inside an expander that is collapsed unless the agent
    # self-corrected, so waiting for visibility would time out on the happy path.
    page.wait_for_selector(".trace-row", state="attached", timeout=settle_ms)
    page.wait_for_timeout(2_500)


def capture(url: str) -> list[Path]:
    """Take the screenshots and return the paths written."""
    from playwright.sync_api import sync_playwright

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2)

        log.info("loading_app", url=url)
        page.goto(url, wait_until="networkidle", timeout=120_000)
        _wait_for_app(page)

        # 1. The landing view: hero, measured results, and the sample questions.
        landing = IMAGE_DIR / "app-landing.png"
        page.screenshot(path=str(landing))
        written.append(landing)
        log.info("captured", image=landing.name)

        # 2. A grounded answer with its citation expanded.
        _ask(page, SIMPLE_QUESTION)
        # Open both the citation and the trace so the screenshot shows the evidence and
        # the route, which is the whole point of the panel.
        for summary in page.locator('[data-testid="stExpander"] summary').all():
            label = summary.inner_text()
            if "rate_limits" in label or "Agent reasoning" in label:
                summary.click()
                page.wait_for_timeout(600)
        page.wait_for_timeout(1_500)
        answer = IMAGE_DIR / "app-answer.png"
        page.screenshot(path=str(answer), full_page=True)
        written.append(answer)
        log.info("captured", image=answer.name)

        # 3. The self-correction path, which is the point of the project. Its trace
        #    expands on its own because the agent rewrote its query.
        page.reload(wait_until="networkidle")
        _wait_for_app(page)
        _ask(page, SELF_CORRECTION_QUESTION, settle_ms=90_000)
        page.wait_for_timeout(2_000)
        trace = IMAGE_DIR / "app-self-correction.png"
        page.screenshot(path=str(trace), full_page=True)
        written.append(trace)
        log.info("captured", image=trace.name)

        browser.close()

    return written


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Capture README screenshots.")
    parser.add_argument("--url", default=LIVE_URL, help="App to screenshot.")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    try:
        written = capture(args.url)
    except Exception as exc:  # noqa: BLE001
        print(f"\nCapture failed: {exc}\n")
        print("Is the app reachable? For a local instance:")
        print("  streamlit run streamlit_app.py")
        return 1

    print("\nWrote:")
    for path in written:
        print(f"  {path.relative_to(PROJECT_ROOT)}  ({path.stat().st_size // 1024} KB)")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
