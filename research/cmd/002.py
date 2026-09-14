page.wait_for_timeout(3000)
print("url:", page.url)
print(shot(page, "002_state"))
print(page.inner_text("body")[:1500])
