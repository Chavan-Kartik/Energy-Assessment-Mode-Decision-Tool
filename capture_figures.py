"""
Capture the six Appendix E figures.

Each figure is cropped to the working pane rather than the whole window. The
manuscript is portrait with a 6.86 in text column, so a full 1440 px window
reduced to that width leaves the interface text too small to read. The pane on
its own is 942 px wide, which at 6.4 in prints at roughly the same text size as
the existing figures in the paper.

The pane is also allowed to grow to its natural height first, so nothing is cut
off at the bottom.

Usage:
    1. Start the tool WITHOUT --reload:   py -m uvicorn app:app --port 8000
    2. Delete assessment_records.db for a clean Figure E4
    3. Run:                               py capture_figures.py
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "figures"
BASE = "http://127.0.0.1:8000"

# Lets the pane size itself to its content instead of to the fixed 1440x900 shell.
GROW = """
  body.capture { display: block !important; background: #ffffff !important; }
  body.capture #shell { width: 1440px !important; height: auto !important;
                        border: none !important; box-shadow: none !important; }
  #body { height: auto !important; align-items: start !important; }
  #pane { height: auto !important; max-height: none !important;
          overflow: visible !important; }
  #status { height: auto !important; }
"""

# Order matters: E4 compares against the run created by E3.
FIGURES = [
    {
        "name": "fig-e1-evidence-gate-item",
        "path": "/?case=gate/held&dim=management_commitment&layer=1&tab=1&capture=1",
        "layer": "Input and evidence",
        "must_see": "Safe access authorization",
    },
    {
        "name": "fig-e2-hold-disposition",
        "path": "/?case=gate/held&run=1&layer=3&tab=0&capture=1",
        "layer": "Decision and governance",
        "must_see": "READINESS IMPROVEMENT / HOLD",
    },
    {
        "name": "fig-e3-self-assessment",
        "path": "/?case=routing/self&run=1&layer=3&tab=0&capture=1",
        "layer": "Decision and governance",
        "must_see": "SELF-ASSESSMENT",
    },
    {
        "name": "fig-e4-run-comparison",
        "path": "/?case=routing/remote&run=1&compare=routing/self&capture=1",
        "layer": "Output and learning",
        "must_see": "REMOTE SPECIALIST",
    },
    {
        "name": "fig-e5-analytics-eem54",
        "path": "/?case=override/onsite&run=1&layer=2&capture=1",
        "layer": "Analytics and robustness",
        "must_see": "66.25",
    },
    {
        "name": "fig-e6-override-decision",
        "path": "/?case=override/onsite&run=1&layer=3&tab=0&capture=1",
        "layer": "Decision and governance",
        "must_see": "ON-SITE EXPERT",
    },
]


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Installing playwright (one-time)...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "playwright"])
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
        from playwright.sync_api import sync_playwright

    OUT.mkdir(exist_ok=True)
    for stale in OUT.glob("fig-*.png"):
        stale.unlink()

    hashes: dict[str, str] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for figure in FIGURES:
            print(f"  {figure['name']:<32}", end=" ", flush=True)
            page = browser.new_page(
                viewport={"width": 1460, "height": 1000},
                device_scale_factor=3,
            )
            try:
                page.goto(BASE + figure["path"], wait_until="domcontentloaded")
                page.wait_for_selector('html[data-ready="1"]', timeout=60000)
                page.locator(".layer.active .t", has_text=figure["layer"]).wait_for(
                    timeout=60000
                )
                page.get_by_text(figure["must_see"], exact=False).first.wait_for(
                    timeout=60000
                )
                page.add_style_tag(content=GROW)
                page.wait_for_timeout(500)

                target = OUT / f"{figure['name']}.png"
                page.locator("#pane").screenshot(path=str(target))
            finally:
                page.close()

            size = page.viewport_size
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            hashes[figure["name"]] = digest
            print(f"{target.stat().st_size:>9,} bytes  sha {digest[:12]}")

        browser.close()

    unique = len(set(hashes.values()))
    print(f"\n{unique} of {len(hashes)} figures are unique.")
    if unique < len(hashes):
        groups: dict[str, list[str]] = {}
        for name, digest in hashes.items():
            groups.setdefault(digest, []).append(name)
        print("ERROR: identical figures found. Do not use them in the paper.")
        for group in groups.values():
            if len(group) > 1:
                print(f"  duplicate: {', '.join(group)}")
        return 1

    print(f"Written to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
