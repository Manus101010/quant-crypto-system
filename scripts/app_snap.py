"""Open the hosted app in a real browser, run Trade Desk on SOL and the Movers scan,
save screenshots + page text to snaps/ (uploaded as a workflow artifact). Read only."""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "https://quantcore.streamlit.app"
OUT = Path("snaps"); OUT.mkdir(exist_ok=True)


def app_frame(page):
    for fr in page.frames:
        if "/~/+/" in fr.url:
            return fr
    return page.main_frame


def wait_text(page, needle, secs=240):
    for _ in range(secs // 5):
        page.wait_for_timeout(5000)
        btn = page.get_by_role("button", name="Yes, get this app back up!")
        if btn.count():
            btn.first.click()
        try:
            t = app_frame(page).inner_text("body", timeout=3000)
            if needle in t:
                return t
        except Exception:  # noqa: BLE001
            pass
    return None


with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1300, "height": 3000})
    pg.goto(f"{BASE}/trade_desk", wait_until="domcontentloaded", timeout=120_000)
    t = wait_text(pg, "Manual Trade Desk")
    print("trade desk loaded:", bool(t))
    pg.screenshot(path=str(OUT / "first.png"), full_page=True)
    for fr in pg.frames:
        try:
            print("FRAME", fr.url[:90], "|", fr.inner_text("body", timeout=3000)[:1500].replace("\n", " / "))
        except Exception as exc:  # noqa: BLE001
            print("FRAME", fr.url[:90], "| (no text)", exc)
    if t:
        fr = app_frame(pg)
        box = fr.get_by_placeholder("e.g. SOL, WIF, PEPE")
        box.fill("SOL"); box.press("Enter")
        t = wait_text(pg, "Grid bot plan", 180)
        pg.wait_for_timeout(15000)
        txt = app_frame(pg).inner_text("body")
        (OUT / "trade_desk.txt").write_text(txt)
        i = txt.find("Your timeframes")
        print("LADDER:", txt[i:i + 900] if i >= 0 else "section missing")
        j = txt.find("Investment per bot")
        print("INVEST:", txt[j:j + 60] if j >= 0 else "missing")
        pg.screenshot(path=str(OUT / "trade_desk.png"), full_page=True)
    pg.goto(f"{BASE}/movers", wait_until="domcontentloaded", timeout=120_000)
    if wait_text(pg, "movers", 180):
        fr = app_frame(pg)
        fr.get_by_role("button", name="Scan movers now").click()
        wait_text(pg, "Top losers", 240)
        pg.wait_for_timeout(5000)
        txt = app_frame(pg).inner_text("body")
        (OUT / "movers.txt").write_text(txt)
        print("MOVERS:", txt[:1500])
        pg.screenshot(path=str(OUT / "movers.png"), full_page=True)
    b.close()
sys.exit(0)
