# Rozpoznanie serwisu info-kierowca.pl

Skrypty użyte do rozpoznania serwisu (wyniki: `specyfikacja.md`, sekcja 6).

| Plik | Opis |
|---|---|
| `explore.py`, `explore2.py` | rozpoznanie bez logowania w headless Chromium (strona logowania, opis usługi, przekierowanie do login.gov.pl) |
| `driver.py` | interaktywny sterownik widocznej przeglądarki: wykonuje fragmenty Pythona wrzucane do `cmd/NNN.py`, wynik zapisuje w `out/NNN.txt`, ruch XHR/fetch loguje do `net.jsonl`; blokuje wywołania tworzące/potwierdzające rezerwację i płatność |
| `cmd/001.py`–`cmd/011.py` | kolejne kroki wspólnego przebiegu po zalogowaniu (logowanie QR → krok „Termin”, test API, pomiar limitu zapytań) |

Uruchomienie (Python + Playwright):

```bash
uv venv .venv && uv pip install --python .venv/bin/python playwright
.venv/bin/python -m playwright install chromium
.venv/bin/python driver.py
```

`driver.py` tworzy obok siebie `profile/`, `out/`, `shots/`, `net.jsonl` — zawierają sesję i dane osobowe,
są wykluczone w `.gitignore` i **nie mogą trafić do repozytorium**.
