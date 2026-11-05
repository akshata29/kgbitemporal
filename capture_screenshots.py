"""Captures the README screenshots by driving the running demo UI (http://127.0.0.1:8765) with Playwright.

Developer-only helper (not shipped in the customer package):
    pip install playwright   # uses the locally installed Microsoft Edge
    python capture_screenshots.py
Starts from freshly seeded data (POST /api/reset), walks the story, and leaves the data reset.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import requests
from playwright.sync_api import Page, sync_playwright

logger = logging.getLogger(__name__)
BASE = "http://127.0.0.1:8765"
OUT = Path(__file__).parent / "docs" / "img"
W = 1440


def settle(page: Page, ms: int = 1500) -> None:
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(ms)


def shot(page: Page, name: str, selector: str | None = None) -> None:
    h = page.evaluate("document.documentElement.scrollHeight")
    page.set_viewport_size({"width": W, "height": min(max(h + 70, 700), 2200)})
    page.wait_for_timeout(400)
    page.screenshot(path=str(OUT / name))
    logger.info("saved %s", name)
    page.set_viewport_size({"width": W, "height": 900})


def tab(page: Page, name: str) -> None:
    page.click(f"#tabs button[data-tab={name}]")
    settle(page)


def persona(page: Page, key: str) -> None:
    page.select_option("#persona", key)
    settle(page)


def preset(page: Page, name: str) -> None:
    page.click(f"[data-preset={name}]")
    settle(page)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    requests.post(f"{BASE}/api/reset", timeout=120).raise_for_status()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": W, "height": 900})
        page.goto(BASE); settle(page, 2500)

        persona(page, "dana")
        shot(page, "01-corpus-query.png")

        page.click("#qTable tr.click >> nth=2"); settle(page, 800)
        shot(page, "02-evidence-drawer.png")
        page.click("#drawerClose")

        page.check("input[name=er][value=false]"); settle(page)
        shot(page, "03-naive-vs-resolved.png")
        page.check("input[name=er][value=true]"); settle(page)

        persona(page, "marcus")
        shot(page, "04-persona-marcus.png")
        persona(page, "dana")

        tab(page, "graph"); page.wait_for_timeout(2500)
        shot(page, "05-graph.png")

        tab(page, "time")
        page.select_option("#entitySel", "E1"); settle(page)
        shot(page, "06-bitemporal-before-correction.png")

        tab(page, "query")
        preset(page, "decision")
        shot(page, "07-as-known-then.png")

        tab(page, "diff"); page.click("#runDiff"); settle(page)
        shot(page, "08-then-vs-now.png")

        preset(page, "today")
        persona(page, "priya")
        tab(page, "review")
        shot(page, "09-review-queue.png")

        page.click("#rTable button[data-key=P1]"); settle(page, 2500)
        tab(page, "time"); page.select_option("#entitySel", "E1"); settle(page)
        shot(page, "10-bitemporal-after-correction.png")

        persona(page, "dana")
        preset(page, "decision")
        tab(page, "diff"); page.click("#runDiff"); settle(page)
        shot(page, "11-then-vs-now-after-correction.png")

        # ---- new features, from freshly seeded data
        requests.post(f"{BASE}/api/reset", timeout=120).raise_for_status()
        page.goto(BASE); settle(page, 2500)
        persona(page, "dana")
        preset(page, "day-one")
        shot(page, "12-day-one-corpus.png")
        preset(page, "today")
        tab(page, "paths"); settle(page, 1200)
        shot(page, "13-variable-depth-paths.png")

        tab(page, "sql"); settle(page, 1500)
        shot(page, "18-sql-real-postgres.png")
        for pid, name in (("pipe-counts", "23-sql-pipeline-counts.png"), ("pipe-trace", "24-sql-document-to-graph.png"), ("users", "25-sql-users-and-roles.png"), ("access-matrix", "26-sql-access-matrix.png"),
                          ("flagship-now", "19-sql-the-full-question.png"), ("flagship-then", "20-sql-as-known-then.png"), ("guards", "21-sql-constraint-and-trigger.png"), ("trigger-proof", "27-sql-trigger-proof.png")):
            page.click(f"#sqlList button[data-id={pid}]"); settle(page, 1500)
            shot(page, name)

        persona(page, "marcus")
        tab(page, "time"); page.select_option("#entitySel", "E2"); settle(page)
        shot(page, "14-timeline-with-actions.png")
        page.click("#tlTable button[data-act=end]"); settle(page, 2500)
        shot(page, "15-period-ended.png")

        persona(page, "dana")
        tab(page, "diff"); page.click("#runDiff"); settle(page)
        shot(page, "16-then-vs-now-period-ended.png")

        persona(page, "priya")
        tab(page, "time"); page.select_option("#entitySel", "E5"); settle(page)
        page.check("#chips input[data-l=HOLDS_INTEREST_IN]"); page.wait_for_timeout(500)
        page.once("dialog", lambda d: d.accept())
        page.click("#tlTable tr:has-text('Carlos Moreno') button[data-act=withdraw]"); settle(page, 2500)
        shot(page, "17-withdrawn.png")

        tab(page, "sql"); page.click("#sqlList button[data-id=history]"); settle(page, 1500)
        shot(page, "22-sql-change-log.png")
        browser.close()
    requests.post(f"{BASE}/api/reset", timeout=120).raise_for_status()
    logger.info("done; data reset")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
