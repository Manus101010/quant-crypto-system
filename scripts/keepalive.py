"""
Keep the Streamlit Community Cloud app awake.

Free apps sleep after ~12h without a real browser visit (a plain HTTP request
doesn't count — Streamlit needs the websocket session). This opens the app in
headless Chromium; if it's asleep it clicks "Yes, get this app back up!" and
waits for the app to load. Run every few hours by .github/workflows/keepalive.yml.
"""
import sys
from playwright.sync_api import sync_playwright

URL = "https://quantcore.streamlit.app/"


def main() -> int:
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(8_000)
        woke = False
        btn = page.get_by_role("button", name="Yes, get this app back up!")
        if btn.count():
            btn.first.click()
            woke = True
            print("app was asleep — clicked wake button")
        # Wait for the app itself to render inside its iframe.
        for _ in range(24):                           # up to ~4 min while it boots
            page.wait_for_timeout(10_000)
            for fr in page.frames:
                try:
                    if "Quant" in (fr.inner_text("body", timeout=2_000) or ""):
                        print(f"app is up ({'woken' if woke else 'was awake'})")
                        b.close()
                        return 0
                except Exception:                     # noqa: BLE001 — frame not ready
                    pass
        print("app did not finish loading in time")
        b.close()
        return 1


if __name__ == "__main__":
    sys.exit(main())
