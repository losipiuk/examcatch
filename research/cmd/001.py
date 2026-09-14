page.wait_for_load_state("networkidle")
page.wait_for_timeout(2000)
print("url:", page.url)
if "/login" in page.url:
    try:
        page.get_by_text("ODRZUĆ WSZYSTKIE").first.click(timeout=5000)
    except Exception as e:
        print("cookie banner not clicked:", e)
    page.get_by_text("login.gov.pl").first.click()
    page.wait_for_url("**login.gov.pl/**", timeout=30000)
    page.wait_for_timeout(2000)
    page.get_by_role("button", name="Aplikacja mObywatel").click()
    page.wait_for_timeout(3000)
    print("url after mObywatel:", page.url)
    print(shot(page, "001_qr"))
else:
    print("already logged in")
    print(shot(page, "001_logged"))
