from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent / "explore"
OUT.mkdir(exist_ok=True)
requests = []


def dump(page, name):
    page.wait_for_timeout(3000)
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
    (OUT / f"{name}.txt").write_text(page.inner_text("body"))
    print(f"=== {name}: {page.url}")
    print(page.inner_text("body")[:2500])


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(locale="pl-PL", viewport={"width": 1400, "height": 900})
    page.on("request", lambda r: requests.append(f"{r.method} {r.url}")
            if r.resource_type in ("xhr", "fetch", "document") else None)

    page.goto("https://info-kierowca.pl/services/reservation", wait_until="networkidle")
    dump(page, "03_services_reservation")

    page.goto("https://info-kierowca.pl/login?returnUrl=%2Freservation", wait_until="networkidle")
    page.wait_for_timeout(2000)
    try:
        page.get_by_text("ODRZUĆ WSZYSTKIE").first.click(timeout=5000)
    except Exception as e:
        print("cookie banner:", e)
    page.get_by_text("login.gov.pl").first.click()
    page.wait_for_load_state("networkidle")
    dump(page, "04_login_gov")
    for el in page.query_selector_all("a, button, [role=button]"):
        txt = (el.inner_text() or "").strip().replace("\n", " ")
        if txt:
            print(f"  [{el.evaluate('e => e.tagName')}] {txt!r}")

    print("=== requests")
    print("\n".join(dict.fromkeys(requests)))
    browser.close()
