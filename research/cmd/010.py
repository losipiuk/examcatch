page.get_by_text("21/10/2026").first.click()
page.wait_for_timeout(2000)
print(shot(page, "010_step2_day"))
txt = page.inner_text("body")
i = txt.find("Wybór daty początkowej")
j = txt.find("Poprzedni krok")
print(txt[i:j][:3000])
print("=== slot components")
for el in page.query_selector_all("app-timetable-exam-slot, app-timetable-exam-card, app-timetable-row-exam, mat-checkbox, mat-expansion-panel, [role=button]"):
    try:
        if el.is_visible():
            print(f"[{el.evaluate('e => e.tagName')}] class={(el.get_attribute('class') or '')[:70]} "
                  f"aria={el.get_attribute('aria-label')} text={(el.inner_text() or '').strip()[:90]!r}")
    except Exception as e:
        print("err", e)
