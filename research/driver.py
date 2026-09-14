"""Interactive exploration driver.

Keeps one headed browser open. Commands are Python snippets dropped into cmd/NNN.py;
output goes to out/NNN.txt. Network traffic (xhr/fetch) is logged to net.jsonl.
Reservation-creating API calls are blocked as a safety net.
"""
import io
import json
import traceback
from contextlib import redirect_stdout
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = Path(__file__).parent
CMD = BASE / "cmd"
OUT = BASE / "out"
SHOTS = BASE / "shots"
for d in (CMD, OUT, SHOTS):
    d.mkdir(exist_ok=True)
NET = (BASE / "net.jsonl").open("a")

BLOCKED = ("Reservations/create", "Reservations/confirm", "Reservations/reschedule",
           "Reservations/cancel", "payments/init")


def block(route):
    print("BLOCKED:", route.request.method, route.request.url, flush=True)
    NET.write(json.dumps({"blocked": route.request.url, "body": route.request.post_data}) + "\n")
    NET.flush()
    route.abort()


def on_response(resp):
    req = resp.request
    if req.resource_type not in ("xhr", "fetch", "eventsource"):
        return
    rec = {"method": req.method, "url": req.url, "status": resp.status,
           "req_headers": req.headers, "req_body": req.post_data,
           "resp_headers": resp.headers}
    try:
        if "json" in resp.headers.get("content-type", ""):
            rec["resp_body"] = resp.json()
    except Exception as e:
        rec["resp_body_err"] = str(e)
    NET.write(json.dumps(rec, ensure_ascii=False) + "\n")
    NET.flush()


def shot(page, name):
    path = SHOTS / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return str(path)


with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        str(BASE / "profile"), headless=False, locale="pl-PL",
        viewport={"width": 1400, "height": 900})
    for pattern in BLOCKED:
        ctx.route(f"**/*{pattern}*", block)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on("response", on_response)
    page.goto("https://info-kierowca.pl/reservation")
    print("READY", flush=True)

    done = set()
    while True:
        for f in sorted(CMD.glob("*.py")):
            if f.name in done:
                continue
            done.add(f.name)
            buf = io.StringIO()
            try:
                with redirect_stdout(buf):
                    exec(f.read_text(), {"page": page, "ctx": ctx, "shot": shot, "json": json})
            except Exception:
                buf.write("\nERROR:\n" + traceback.format_exc())
            (OUT / f"{f.stem}.txt").write_text(buf.getvalue() or "(no output)")
            if f.read_text().startswith("# STOP"):
                ctx.close()
                raise SystemExit
        page.wait_for_timeout(500)
