page.get_by_text("Zarezerwuj termin egzaminu").first.click()
page.wait_for_load_state("networkidle")
page.wait_for_timeout(3000)
print("url:", page.url)
print(shot(page, "003_step1"))
main = page.locator("main") if page.locator("main").count() else page.locator("body")
print(main.inner_text()[:3000])
print("=== controls")
for el in page.query_selector_all("mat-select, mat-radio-button, mat-checkbox, input, button, mat-button-toggle, [role=radio], [role=combobox], [role=option]"):
    try:
        if not el.is_visible():
            continue
        print(f"[{el.evaluate('e => e.tagName')}] id={el.get_attribute('id')} name={el.get_attribute('name')} "
              f"formcontrolname={el.get_attribute('formcontrolname')} aria-label={el.get_attribute('aria-label')} "
              f"text={(el.inner_text() or '').strip()[:80]!r}")
    except Exception as e:
        print("err", e)
