btns = page.locator("button:visible", has_text="Zapisz i przejdź dalej")
print("visible next buttons:", btns.count())
btns.first.click()
page.wait_for_load_state("networkidle")
page.wait_for_timeout(5000)
print("url:", page.url)
print(shot(page, "007_step2"))
txt = page.inner_text("body")
i = txt.find("Zwiń panel")
print(txt[i:i + 6000])
print("=== controls step2")
for el in page.query_selector_all("mat-select, mtx-select, mat-radio-button, mat-checkbox, input, button, mat-button-toggle, mat-datepicker-toggle, app-timetable-exam-slot, app-timetable-exam-card"):
    try:
        if el.is_visible():
            print(f"[{el.evaluate('e => e.tagName')}] id={el.get_attribute('id')} name={el.get_attribute('name')} "
                  f"fcn={el.get_attribute('formcontrolname')} aria={el.get_attribute('aria-label')} "
                  f"class={(el.get_attribute('class') or '')[:60]} text={(el.inner_text() or '').strip()[:60]!r}")
    except Exception as e:
        print("err", e)
