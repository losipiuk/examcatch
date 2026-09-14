print("category text:", page.locator("#category").inner_text().strip(), "| disabled:", page.locator("#category").get_attribute("aria-disabled"))
page.get_by_text("Pokaż tylko najbliższe terminy dla ośrodków WORD w okolicy").click()
page.wait_for_timeout(1000)
print(shot(page, "006_step1_filled"))
page.get_by_text("Zapisz i przejdź dalej").click()
page.wait_for_load_state("networkidle")
page.wait_for_timeout(4000)
print("url:", page.url)
print(shot(page, "006_step2"))
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
