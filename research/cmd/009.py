from pathlib import Path

def controls(tag):
    print(f"=== controls {tag}")
    for el in page.query_selector_all("mat-select, mtx-select, mat-radio-button, input, button"):
        try:
            if el.is_visible():
                print(f"[{el.evaluate('e => e.tagName')}] id={el.get_attribute('id')} fcn={el.get_attribute('formcontrolname')} "
                      f"aria={el.get_attribute('aria-label')} text={(el.inner_text() or '').strip()[:60]!r}")
        except Exception as e:
            print("err", e)

page.locator("button:visible", has_text="Poprzedni krok").first.click()
page.wait_for_timeout(2500)
page.get_by_text("Wybierz ośrodek WORD i pokaż wszystkie terminy egzaminów").click()
page.wait_for_timeout(2500)
print(shot(page, "009_step1_single_word"))
controls("step1 single-word mode")

# try to pick Bemowo: a select with WORD list, or a clickable entry in the nearby list / map
picked = False
for sel in page.query_selector_all("mtx-select, mat-select"):
    if sel.is_visible() and sel.get_attribute("id") not in ("profileNumber", "category"):
        sel.click()
        page.wait_for_timeout(1500)
        inp = page.locator(f"#{sel.get_attribute('id')}-input") if sel.get_attribute("id") else None
        try:
            if inp is not None and inp.count():
                inp.fill("Bemowo")
                page.wait_for_timeout(1500)
        except Exception as e:
            print("fill err", e)
        opts = [o for o in page.query_selector_all("[role=option], .ng-option") if o.is_visible()]
        print("word options:", [o.inner_text().strip()[:60] for o in opts][:10])
        target = next((o for o in opts if "Bemowo" in o.inner_text()), None)
        if target:
            target.click()
            picked = True
            page.wait_for_timeout(1500)
        break
if not picked:
    try:
        page.get_by_text("WORD Warszawa M/E Bemowo").first.click()
        picked = True
        page.wait_for_timeout(1500)
    except Exception as e:
        print("click Bemowo text err", e)
print("picked Bemowo:", picked)
print(shot(page, "009_step1_bemowo"))

if picked:
    page.locator("button:visible", has_text="Zapisz i przejdź dalej").first.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(4000)
    try:
        page.get_by_text("Egzamin praktyczny", exact=True).first.click()
        page.wait_for_timeout(3000)
    except Exception as e:
        print("practice radio err", e)
    print(shot(page, "009_step2_bemowo"))
    txt = page.inner_text("body")
    i = txt.find("Wybór terminu egzaminu")
    j = txt.find("Poprzedni krok")
    print(txt[i:j][:4000])
    controls("step2 single-word")

print("=== OneCenterExam calls captured")
for line in Path("net.jsonl").read_text().splitlines():
    r = json.loads(line)
    if "OneCenterExam" in r.get("url", ""):
        body = r.get("req_body")
        try:
            b = json.loads(body)
            b["profileNumber"] = "<masked>"
            body = json.dumps(b)
        except Exception:
            pass
        print(r["status"], body)
