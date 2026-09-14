import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent / "explore"
OUT.mkdir(exist_ok=True)
requests = []


def dump(page, name):
    page.wait_for_timeout(3000)
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
    (OUT / f"{name}.txt").write_text(page.inner_text("body"))
    (OUT / f"{name}.html").write_text(page.content())
    print(f"=== {name}: {page.url}")
    for el in page.query_selector_all("a, button, [role=button]"):
        txt = (el.inner_text() or "").strip().replace("\n", " ")
        if txt:
            print(f"  [{el.evaluate('e => e.tagName')}] {txt!r} href={el.get_attribute('href')}")


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(locale="pl-PL", viewport={"width": 1400, "height": 900})
    page.on("request", lambda r: requests.append(f"{r.method} {r.resource_type} {r.url}")
            if r.resource_type in ("xhr", "fetch", "document") else None)
    page.goto("https://info-kierowca.pl/reservation", wait_until="networkidle")
    dump(page, "01_start")
    try:
        page.get_by_text("Zarezerwuj termin egzaminu").first.click()
        page.wait_for_load_state("networkidle")
        dump(page, "02_after_click")
    except Exception as e:
        print("click failed:", e, file=sys.stderr)
    print("=== requests")
    print("\n".join(dict.fromkeys(requests)))
    browser.close()
