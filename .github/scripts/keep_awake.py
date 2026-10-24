"""Visit the deployed Streamlit app so Community Cloud doesn't put it to sleep.

Run on a schedule by .github/workflows/keep-awake.yml. A plain HTTP request doesn't count as a
visit (Streamlit only counts a browser session with an open websocket), so this opens the page in
headless Chrome, clicks the wake-up button if the app is already asleep, and waits until the app
itself has rendered. Exits non-zero if it never does, so a failed run shows up in GitHub.

The app must be set to public on share.streamlit.io; a private app shows a login page instead.
"""
import os
import re
import sys
import time

from playwright.sync_api import sync_playwright

APP_URL = os.environ.get("APP_URL", "https://cloud-init-maker-jazz.streamlit.app/")
# "chrome" uses an installed Google Chrome (GitHub's Ubuntu runners have one) instead of
# Playwright's own Chromium, which skips a download that sometimes takes 10+ minutes on a runner.
BROWSER_CHANNEL = os.environ.get("BROWSER_CHANNEL") or None
WAKE_BUTTON = re.compile(r"get this app back up", re.IGNORECASE)
# A cold start reinstalls requirements, so allow a few minutes.
APP_LOAD_TIMEOUT_S = 5 * 60
POLL_INTERVAL_MS = 5000


def app_rendered(page) -> bool:
    """True once Streamlit's root element exists in the page or in the iframe that hosts the app."""
    return any(frame.locator('[data-testid="stApp"]').count() for frame in page.frames)


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=BROWSER_CHANNEL)
        page = browser.new_page()
        print(f"Opening {APP_URL}")
        page.goto(APP_URL, wait_until="domcontentloaded", timeout=60_000)

        deadline = time.monotonic() + APP_LOAD_TIMEOUT_S
        woke = False
        while time.monotonic() < deadline:
            if app_rendered(page):
                print("App was asleep; woke it up." if woke else "App is awake.")
                # Stay connected briefly so the visit registers as a real session.
                page.wait_for_timeout(15_000)
                browser.close()
                return 0
            button = page.get_by_role("button", name=WAKE_BUTTON)
            if not woke and button.count() and button.first.is_visible():
                print("App is asleep; clicking the wake-up button.")
                button.first.click()
                woke = True
            page.wait_for_timeout(POLL_INTERVAL_MS)

        page.screenshot(path="keep-awake-failure.png", full_page=True)
        browser.close()
        print(f"App did not finish loading within {APP_LOAD_TIMEOUT_S}s.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
