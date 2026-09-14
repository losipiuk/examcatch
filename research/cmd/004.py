page.get_by_text("PKK - Profil kandydata na kierowcę (PKK)").click()
page.wait_for_timeout(1500)
print("=== after PKK radio; selects:")
for el in page.query_selector_all("mtx-select, mat-select"):
    if el.is_visible():
        print(f"  id={el.get_attribute('id')} fcn={el.get_attribute('formcontrolname')} text={(el.inner_text() or '').strip()!r}")
page.locator("#category").click()
page.wait_for_timeout(1500)
opts = [o.inner_text().strip() for o in page.query_selector_all("[role=option], .ng-option") if o.is_visible()]
print("category options:", opts)
print(shot(page, "004_category_open"))
target = next((o for o in page.query_selector_all("[role=option], .ng-option") if o.is_visible() and "B" in o.inner_text()), None)
if target:
    target.click()
    page.wait_for_timeout(1500)
else:
    page.keyboard.press("Escape")
print("=== selects after category:")
for el in page.query_selector_all("mtx-select, mat-select"):
    if el.is_visible():
        print(f"  id={el.get_attribute('id')} fcn={el.get_attribute('formcontrolname')} text={(el.inner_text() or '').strip()!r}")
page.get_by_text("Pokaż tylko najbliższe terminy dla ośrodków WORD w okolicy").click()
page.wait_for_timeout(1500)
print(shot(page, "004_step1_filled"))
page.get_by_role("button", name=re.compile("Zapisz i przejdź dalej")).click() if False else page.get_by_text("Zapisz i przejdź dalej").click()
page.wait_for_load_state("networkidle")
page.wait_for_timeout(4000)
print("url:", page.url)
print(shot(page, "004_step2"))
txt = page.inner_text("body")
i = txt.find("Rezerwacja egzaminu")
print(txt[i:i + 4000])
print("=== controls step2")
for el in page.query_selector_all("mat-select, mtx-select, mat-radio-button, mat-checkbox, input, button, mat-button-toggle, [role=radio], mat-datepicker-toggle"):
    try:
        if el.is_visible():
            print(f"[{el.evaluate('e => e.tagName')}] id={el.get_attribute('id')} name={el.get_attribute('name')} "
                  f"fcn={el.get_attribute('formcontrolname')} aria={el.get_attribute('aria-label')} "
                  f"text={(el.inner_text() or '').strip()[:60]!r}")
    except Exception as e:
        print("err", e)
