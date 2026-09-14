import re, time
from pathlib import Path

# 1) UI: filter to practical exams
page.get_by_text("Egzamin praktyczny", exact=True).first.click()
page.wait_for_timeout(3000)
print(shot(page, "008_step2_practice"))
txt = page.inner_text("body")
i = txt.find("Wybór terminu egzaminu")
j = txt.find("Poprzedni krok")
print(txt[i:j])

# 2) API from page context: reuse the frontend's MultipleCentersExams request body
last = None
for line in Path("net.jsonl").read_text().splitlines():
    r = json.loads(line)
    if "Schedules/user/MultipleCentersExams" in r.get("url", "") and r.get("req_body"):
        last = json.loads(r["req_body"])
print("frontend body keys:", list(last) if last else None,
      "| profileType:", last and last.get("profileType"), "| category:", last and last.get("category"),
      "| startDate:", last and last.get("startDate"), "| organizationId:", last and last.get("organizationId"))

JS = """async ({url, body}) => {
  const t0 = performance.now();
  const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json', 'Accept': 'application/json'}, body: JSON.stringify(body)});
  const h = {}; r.headers.forEach((v, k) => h[k] = v);
  let data = null; try { data = await r.json(); } catch (e) {}
  return {status: r.status, ms: Math.round(performance.now() - t0), headers: h, data};
}"""

def summarize(data):
    out = []
    days = data.get("examCollectionForDay") if isinstance(data, dict) else None
    if days is None:
        return f"unexpected shape: {json.dumps(data, ensure_ascii=False)[:600]}"
    out.append(f"top keys={list(data)} days={len(days)}")
    if days:
        out.append("day sample: " + json.dumps(days[0], ensure_ascii=False)[:1200])
    for d in days:
        for c in d.get("examCollections", []):
            for k, v in c.items():
                if isinstance(v, list):
                    for e in v:
                        out.append(f"  {d.get('date')} {k}: " + json.dumps(e, ensure_ascii=False)[:250])
    return "\n".join(out[:80])

if last:
    for org in (26, 25):
        body = dict(last, organizationId=org)
        res = page.evaluate(JS, {"url": "/bknd/exam/api/v1/Schedules/user/OneCenterExam", "body": body})
        print(f"\n### OneCenterExam org={org} status={res['status']} ms={res['ms']}")
        print("resp headers:", {k: v for k, v in res["headers"].items() if k.lower() not in ("date", "strict-transport-security", "x-content-type-options", "cross-origin-opener-policy", "cross-origin-embedder-policy", "cross-origin-resource-policy")})
        print(summarize(res["data"]))
    # small burst to observe rate limiting headers (5 calls, 1 per second)
    print("\n### burst")
    for n in range(5):
        res = page.evaluate(JS, {"url": "/bknd/exam/api/v1/Schedules/user/MultipleCentersExams", "body": last})
        print(n, res["status"], res["ms"], {k: v for k, v in res["headers"].items() if "rate" in k.lower() or "retry" in k.lower()})
        page.wait_for_timeout(1000)
