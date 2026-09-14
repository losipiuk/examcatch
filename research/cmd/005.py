def visible_options():
    return [o for o in page.query_selector_all("[role=option], .ng-option") if o.is_visible()]

def pick(select_id, want=None):
    page.locator(f"#{select_id}").click()
    page.wait_for_timeout(1500)
    opts = visible_options()
    print(f"{select_id} options count={len(opts)} labels(masked)=",
          ["".join("#" if c.isdigit() else c for c in o.inner_text().strip()) for o in opts])
    target = next((o for o in opts if want is None or o.inner_text().strip() == want), None)
    if target:
        target.click()
        page.wait_for_timeout(1500)
    else:
        page.keyboard.press("Escape")

pick("profileNumber")
pick("category", "B")
page.get_by_text("Pokaż tylko najbliższe terminy dla ośrodków WORD w okolicy").click()
page.wait_for_timeout(1000)
print(shot(page, "005_step1_filled"))
page.get_by_text("Zapisz i przejdź dalej").click()
page.wait_for_load_state("networkidle")
page.wait_for_timeout(4000)
print("url:", page.url)
print(shot(page, "005_step2"))
txt = page.inner_text("body")
i = txt.find("Zwiń panel")
print(txt[i:i + 5000])
print("=== controls step2")
for el in page.query_selector_all("mat-select, mtx-select, mat-radio-button, mat-checkbox, input, button, mat-button-toggle, mat-datepicker-toggle, app-timetable-exam-slot, app-timetable-exam-card"):
    try:
        if el.is_visible():
            print(f"[{el.evaluate('e => e.tagName')}] id={el.get_attribute('id')} name={el.get_attribute('name')} "
                  f"fcn={el.get_attribute('formcontrolname')} aria={el.get_attribute('aria-label')} "
                  f"text={(el.inner_text() or '').strip()[:60]!r}")
    except Exception as e:
        print("err", e)
