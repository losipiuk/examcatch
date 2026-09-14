# ExamCatch — specyfikacja

> Dokument roboczy. Uzupełniany na bieżąco na podstawie wymagań.

## 1. Cel projektu

Aplikacja automatycznie **rezerwuje** termin **egzaminu praktycznego** na prawo jazdy (kat. B) w serwisie
[info-kierowca.pl](https://info-kierowca.pl/reservation), wybierając najwcześniejszy termin
spełniający kryteria z sekcji 2.4.

Aplikacja **nie dokonuje płatności** — doprowadza proces rezerwacji do ostatniego kroku przed płatnością,
a płatność użytkownik kończy ręcznie.

## 2. Wymagania funkcjonalne

### 2.1. Logowanie i sesja

- Formularz rezerwacji **wymaga zalogowania**.
- Logowanie odbywa się przez **aplikację mObywatel** (skanowanie kodu QR).
- Aplikacja **otwiera widoczne okno przeglądarki** na potrzeby logowania — kod QR wyświetla sam serwis.
  Użytkownik skanuje go w mObywatelu na telefonie.
- Po potwierdzeniu logowania w mObywatelu aplikacja kontynuuje automatycznie.
- **Zapamiętywanie sesji** — aplikacja próbuje zachować sesję (np. profil przeglądarki / cookies)
  między uruchomieniami (_best effort_). Ze względu na krótki czas życia sesji (6.2) po restarcie zwykle
  potrzebne będzie ponowne logowanie — jest to akceptowalne.
- **Wygaśnięcie sesji** (przy starcie lub w trakcie działania):
  1. aplikacja wyświetla informację o wygaśnięciu sesji i wysyła ważne powiadomienie (2.10),
  2. czeka na **potwierdzenie przez użytkownika**,
  3. ponownie przechodzi przez flow logowania (QR), po czym wraca do przerwanej czynności.

### 2.2. Przebieg rezerwacji (automatyczne przeklikanie flow)

1. Zalogowanie (2.1).
2. Start flow: przycisk **„Zarezerwuj termin egzaminu”** w menu po lewej stronie.
3. Aplikacja automatycznie przechodzi przez kolejne kroki formularza rezerwacji
   (rzeczywiste kroki serwisu — patrz 6.3):
   1. **„Profil i WORD”** (szczegóły UI — 6.7.2)
      - **Rodzaj profilu** — PKK.
      - **Numer profilu** — z listy. Oczekiwana jest **dokładnie jedna** pozycja; jeśli jest **więcej niż jedna**
        (lub żadna) — aplikacja **kończy działanie z błędem**.
      - **Kategoria** — uzupełnia się automatycznie z profilu (B); pole jest zablokowane.
      - **Tryb wyboru ośrodka** — „Wybierz ośrodek WORD i pokaż wszystkie terminy egzaminów”
        (tryb „najbliższe terminy” pokazuje tylko jeden najbliższy termin na ośrodek — niewystarczające).
      - **Ośrodek WORD** — ten, w którym znaleziono wybrany termin (2.5). Jeden przebieg flow = jeden ośrodek.
   2. **„Termin”**
      - **Rodzaj egzaminu** — **Egzamin praktyczny**.
      - **Data rozpoczęcia** — data najwcześniejszego dopuszczalnego terminu, czyli dzień z chwili
        „teraz + minimalny czas do startu” (2.4), **nawet jeśli serwis podpowiada późniejszą** (domyślnie dziś + 2 dni).
        To samo `startDate` jest używane w zapytaniach API (2.7.1).
      - Jeśli serwis odrzuci wcześniejszą datę (błąd w UI lub 400 z API) — aplikacja używa najwcześniejszej
        daty akceptowanej przez serwis i informuje o tym na ekranie. _Zachowanie do sprawdzenia przy implementacji
        (1 zapytanie)._
      - **Wybór terminu** — rozwinięcie panelu dnia i zaznaczenie wiersza z godziną zgodnie z kryteriami (2.4).
        Jeśli brak pasującego terminu — patrz 2.7.
   3. **„Język egzaminu i pojazd OSK”**
      - Język egzaminu — zawsze **polski**.
      - Dane pojazdu OSK — opcjonalne, **pomijane**.
   4. **„Podsumowanie”** — aplikacja **zatwierdza** dane.
   5. **„Potwierdzenie”** — aplikacja czeka na potwierdzenie rezerwacji przez serwis
      (status „Wstępna rezerwacja” / `PlaceReserved`). Błąd na tym etapie = termin nie został zablokowany
      (np. ktoś był szybszy) → powrót do wyszukiwania.
   6. **„Płatność”** — **punkt zatrzymania**. Aplikacja **nie przechodzi do bramki płatności**.

Flow nie wymaga podawania żadnych dodatkowych danych osobowych poza wyborem PKK.

### 2.3. Rezerwacja i przekazanie użytkownikowi

- Dojście do kroku **„Płatność”** (tuż przed płatnością) **bez błędu** oznacza, że termin jest
  **zarezerwowany na 30 minut** (status „Wstępna rezerwacja”, 6.5).
- W tym czasie użytkownik musi ręcznie dokończyć płatność.
- Rezerwacja jest widoczna w interfejsie serwisu — zamknięcie zakładki nie powoduje jej utraty.
- Aplikacja przekazuje użytkownikowi (ważne powiadomienie, 2.10):
  - **link do konkretnej rezerwacji** (jeśli uda się go ustalić — nie jest kluczowy, rezerwację można
    odnaleźć w interfejsie serwisu po zalogowaniu),
  - ośrodek, datę i godzinę egzaminu,
  - godzinę, do której trzeba opłacić rezerwację.
- **Przypomnienia o płatności** — w trakcie 30-minutowego okna aplikacja wysyła przypomnienie
  **co 5 minut** (ważne powiadomienie, 2.10; interwał konfigurowalny).
- Aplikacja **nie sprawdza** w serwisie, czy rezerwacja została opłacona.
- **Potwierdzenie płatności w CLI** — po opłaceniu rezerwacji użytkownik potwierdza to w aplikacji
  (np. klawisz / komenda w terminalu). Wtedy:
  - przypomnienia o płatności są zatrzymywane,
  - aplikacja przechodzi do monitoringu wcześniejszych terminów (2.8).
- **Brak potwierdzenia w ciągu 30 minut** — rezerwacja jest uznawana za **wygasłą**: aplikacja wysyła
  ważne powiadomienie (2.10) i **wraca do szukania i rezerwowania** terminu (2.2).

### 2.4. Kryteria wyboru terminu

Warunki konieczne (termin niespełniający któregokolwiek jest odrzucany):

1. **Godzina startu egzaminu** — w przedziale **10:00–15:00** (konfigurowalne).
2. **Minimalny czas do startu** — od chwili sprawdzenia do startu egzaminu musi upłynąć
   co najmniej **6 godzin** (konfigurowalne).
3. **Okno wyszukiwania** — termin w ciągu najbliższych N dni (2.6).
4. **Ośrodek** — z listy skonfigurowanych ośrodków (2.5).

Wybór spośród terminów spełniających warunki: **najwcześniejszy termin** wygrywa.

> Warunek „brak egzaminów po ciemku” został zastąpiony przedziałem godziny startu — osobne sprawdzanie
> wschodu/zachodu słońca nie jest potrzebne.

### 2.5. Ośrodki egzaminacyjne

- Lista ośrodków jest **konfigurowalna** (2.9).
- Domyślnie / na pierwszym etapie — wyłącznie ośrodki w Warszawie:
  - **WORD Warszawa M/E Bemowo**
  - **WORD Warszawa M/E Odlewnicza**
- Przyszłe rozszerzenie: ośrodki spoza Warszawy, z uwzględnieniem czasu dojazdu.
- **Ośrodek niezgodny z PKK** — serwis odrzuca rezerwację w WORD innym niż ten, w którym znajduje się PKK (6.7.6).
  Po takim odrzuceniu aplikacja **pomija ten ośrodek** do końca działania i wysyła ważne powiadomienie (2.10);
  jeśli nie zostanie żaden ośrodek — kończy działanie z błędem.

### 2.6. Okno wyszukiwania

- Aplikacja szuka terminów **w ciągu najbliższych N dni** od chwili sprawdzenia.
- `N` jest konfigurowalne, domyślnie **14 dni**.

### 2.7. Ponawianie wyszukiwania

- Jeśli nie ma pasującego terminu, aplikacja **ponawia próby aż do skutku**.
- Sprawdzanie odbywa się przez wywołania API terminów **z wnętrza zalogowanej sesji przeglądarki**
  (te same ciasteczka, nagłówki i odcisk TLS co frontend). Samą rezerwację aplikacja wykonuje przez klikanie w UI (2.2).
  Uzasadnienie — 6.6.
- Serwis pozwala na **10 zapytań na godzinę na endpoint** (6.7.4) — sprawdzanie co minutę jest niemożliwe.
  Strategia wykorzystuje to, że dwa endpointy mają **osobne limity**.

#### 2.7.1. Strategia dwustopniowa (dotyczy też monitoringu 2.8)

1. **Wykrywacz** — `MultipleCentersExams` dla wszystkich skonfigurowanych ośrodków jednym zapytaniem,
   domyślnie **co 7 min** (≈ 8–9 zapytań/h). Zwraca **najbliższy** termin praktyczny per ośrodek.
   Endpoint wymaga **dokładnie 5 ośrodków** — lista jest dopełniana innymi ośrodkami (wyniki odrzucane);
   przy więcej niż 5 skonfigurowanych ośrodkach — jedno zapytanie na każde 5.
   Endpoint **nie widzi terminów daleko w przyszłości** (14.09 pokazał termin za 29 dni, ale nie termin za 35 dni
   widoczny w pełnym harmonogramie; przyjęty zasięg: 28 dni). Brak najbliższego terminu oznacza brak terminów
   w zasięgu — jeśli okno wyszukiwania (2.6) jest dłuższe niż zasięg, wykonywane jest cykliczne pełne sprawdzenie.
2. **Pełne sprawdzenie** — `OneCenterExam` (wszystkie terminy ośrodka), wykonywane **tylko gdy potrzeba**:
   - najbliższy termin praktyczny w którymś ośrodku **zmienił się** od poprzedniego wykrywacza
     i mieści się w oknie wyszukiwania (2.6), lub
   - najbliższy termin mieści się w oknie, ale nie spełnia pozostałych kryteriów (np. godzina spoza 10–15),
     więc w tym samym oknie mogą pojawić się inne terminy — wtedy pełne sprawdzenie **cyklicznie**,
     domyślnie nie częściej niż **co 15 min**.
   - Jeśli najbliższy termin jest **poza oknem** wyszukiwania — pełne sprawdzenie nie jest potrzebne
     (w oknie na pewno nic nie ma).
   - Jeśli najbliższy termin z wykrywacza **sam spełnia kryteria** — można przejść od razu do rezerwacji (2.2)
     bez pełnego sprawdzenia.
3. **`OneCenterExam` przyjmuje tylko jeden ośrodek** (`[26, 25]` → 400, zweryfikowane) — pełne sprawdzenie
   wykonywane osobno per ośrodek (tylko dla ośrodków, które tego wymagają).

#### 2.7.2. Budżet zapytań

- Aplikacja śledzi `X-RateLimit-Remaining` / `X-RateLimit-Reset` dla każdego endpointu osobno.
- **Rezerwa na rezerwację**: dla `OneCenterExam` aplikacja zostawia co najmniej **2 zapytania** w bieżącym oknie
  (przebieg flow w UI wywołuje ten endpoint przy wejściu w krok „Termin”). Pełne sprawdzenie, które zeszłoby
  poniżej rezerwy, jest odkładane do resetu okna.
- Dla wykrywacza aplikacja zostawia **1 zapytanie** zapasu.
- Po wyczerpaniu budżetu aplikacja czeka do `X-RateLimit-Reset` i informuje o tym na ekranie (mniej istotne).

### 2.8. Monitoring wcześniejszych terminów po rezerwacji

- Po zarezerwowaniu terminu i potwierdzeniu płatności przez użytkownika (2.3) aplikacja **działa dalej** i cyklicznie (z tym samym interwałem co 2.7)
  sprawdza, czy nie pojawiły się **wcześniejsze** terminy niż zarezerwowany (spełniające kryteria 2.4).
- Aplikacja **nie rezerwuje** takich terminów — jedynie **powiadamia** użytkownika (ważne powiadomienie, 2.10).
- Powiadomienie wysyłane jest **o każdym nowym lepszym terminie**, który się pojawi
  (ten sam termin nie jest zgłaszany wielokrotnie).
- Monitoring może działać w tej samej sesji przeglądarki — opuszczenie kroku „Płatność” nie anuluje rezerwacji.
- Decyzja należy do użytkownika: jeśli uzna, że wcześniejsze terminy zwalniają się często, sam anuluje
  poprzednią rezerwację i uruchomi aplikację ponownie z mniejszym oknem wyszukiwania (2.6).
- Monitoring trwa **do ręcznego zatrzymania aplikacji (Ctrl+C)**.

### 2.9. Konfiguracja

**Cała konfiguracja w jednym pliku YAML.** Parametry (na ten moment):

| Parametr | Opis | Domyślnie |
|---|---|---|
| ośrodki | lista WORD-ów branych pod uwagę (2.5) | Bemowo, Odlewnicza |
| okno wyszukiwania | liczba dni od teraz (2.6) | 14 |
| przedział godziny startu | od–do, dopuszczalna godzina rozpoczęcia egzaminu (2.4) | 10:00–15:00 |
| minimalny czas do startu | minimalny odstęp od teraz do startu egzaminu (2.4) | 6 h |
| interwał wykrywacza | co ile wołać `MultipleCentersExams` (2.7.1) | 7 min |
| min. odstęp pełnego sprawdzenia | minimalny odstęp cyklicznych `OneCenterExam` (2.7.1) | 15 min |
| rezerwa zapytań na rezerwację | ile zapytań `OneCenterExam` zostawić w oknie (2.7.2) | 2 |
| interwał przypomnień o płatności | co ile przypominać w trakcie 30-min okna (2.3) | 5 min |
| e-mail | serwer SMTP, port, login, hasło, nadawca, odbiorca (2.10) | — |
| CallMeBot (WhatsApp) | numer telefonu, klucz API (2.10) | — |

**Zmienne środowiskowe** — każda wartość w YAML (w szczególności sekrety: hasło SMTP, klucz CallMeBot)
może być podana na dwa sposoby:

- **wartość wpisana wprost**, np. `password: "tajne-haslo"`,
- **odwołanie do zmiennej środowiskowej** w składni `${NAZWA_ZMIENNEJ}`, np. `password: "${EXAMCATCH_SMTP_PASSWORD}"`.

Jeśli wskazana zmienna środowiskowa nie jest ustawiona — aplikacja kończy działanie z czytelnym błędem przy starcie.

### 2.10. Powiadomienia

Dwa poziomy ważności:

| Poziom | Kanał | Przykłady |
|---|---|---|
| **Mniej istotne** | tylko ekran (konsola) | kolejne sprawdzenie, brak terminów, postęp przez kroki flow |
| **Istotne** | ekran **+ e-mail + WhatsApp** (jednocześnie) | zarezerwowano termin (z linkiem i terminem płatności), przypomnienie o płatności, wygaśnięcie rezerwacji, pojawienie się wcześniejszego terminu, wygaśnięcie sesji (wymaga działania), błąd krytyczny (np. więcej niż jeden PKK) |

Kanały istotnych powiadomień (oba działają jednocześnie, konfiguracja w YAML):

- **E-mail** — wysyłka przez SMTP.
- **WhatsApp** — przez **CallMeBot** (jednorazowa aktywacja z telefonu użytkownika, potem wywołanie HTTP z kluczem API).

Niepowodzenie wysyłki jednym kanałem nie może blokować drugiego ani przerywać działania aplikacji
(błąd jest logowany na ekranie).

## 3. Wymagania niefunkcjonalne

- Aplikacja działa długo (do Ctrl+C) — musi być odporna na przejściowe błędy sieci / serwisu
  (błąd pojedynczego sprawdzenia nie kończy działania, ponowienie w kolejnym cyklu).
- Zatrzymanie przez Ctrl+C kończy działanie w sposób czysty (zamknięcie przeglądarki).
- **Limit zapytań** — serwis ma rate limiting (6.6). Po odpowiedzi **429** aplikacja wstrzymuje zapytania
  do czasu z nagłówka `X-RateLimit-Reset` (a bez nagłówka — z rosnącym odstępem), informuje o tym na ekranie
  i wznawia pracę. Nie wolno odpytywać częściej niż skonfigurowany interwał.
  Limit: **10 zapytań na okno 3600 s**, liczony osobno dla każdego endpointu (6.7.4). Aplikacja śledzi
  `X-RateLimit-Remaining` i nie schodzi do zera (zapas na przebieg rezerwacji).
- **Jedna karta aplikacji** — serwis blokuje drugą otwartą kartę w tej samej przeglądarce (6.6);
  aplikacja działa w **jednej karcie**.

## 4. Technologie i architektura

- **Aplikacja CLI w Pythonie.**
- Integracja z serwisem: strona https://info-kierowca.pl/reservation — **podejście hybrydowe**
  w jednej przeglądarce sterowanej przez **Playwright**:
  - logowanie (QR mObywatel) i rezerwacja — klikanie w UI,
  - cykliczne sprawdzanie terminów — wywołania API z kontekstu zalogowanej strony.
- Przeglądarka uruchamiana w trybie **widocznym** (co najmniej na czas logowania przez QR);
  trwały profil przeglądarki do zachowania sesji.
- Konfiguracja: jeden plik YAML (ścieżka podawana parametrem CLI).
- Powiadomienia: SMTP (e-mail) + CallMeBot (WhatsApp).

## 5. Otwarte pytania

_(brak)_

## 6. Wyniki rozpoznania serwisu (2026-09-14)

Rozpoznanie wykonane bez logowania: headless Chromium (Playwright) + analiza publicznego kodu frontendu
(`main-*.js`, wersja aplikacji 2.8.0). Część za logowaniem zweryfikowana we wspólnym przebiegu — 6.7.

### 6.1. Logowanie

- `https://info-kierowca.pl/reservation` bez sesji przekierowuje na `/login?returnUrl=%2Freservation`.
- Na stronie logowania jest **baner cookies** (przyciski „AKCEPTUJ WSZYSTKIE” / „ODRZUĆ WSZYSTKIE”) — trzeba go zamknąć.
- Dwie metody: **eDO App** oraz **login.gov.pl**.
- Ścieżka mObywatel: karta **„login.gov.pl”** → przekierowanie na `login.gov.pl` → przycisk
  **„Aplikacja mObywatel”** („Skanuj kod QR za pomocą aplikacji mObywatel”) → kod QR.
- Po zalogowaniu powrót na `returnUrl` (`/reservation`).

### 6.2. Sesja

- `GET /bknd/auth/api/v1/jwt/timing` (publiczne):
  `jwtTtlSeconds: 900`, `jwtRefreshBeforeExpirySeconds: 120`, `frontendInactivitySeconds: 600`.
- Token trzymany w ciasteczku `__Secure-PUDOJT` (ciasteczko sesyjne, `SameSite=Strict`).
- Wniosek: sesja wygasa po ~10 min bezczynności; aplikacja musi utrzymywać aktywność.

### 6.3. Kroki formularza rezerwacji

Zgodnie z kodem frontendu (`stepsDefinitions`) i opisem usługi (`/services/reservation`):

| # | ID kroku | Etykieta | Zawartość |
|---|---|---|---|
| 1 | `Init` | Profil i WORD | rodzaj profilu (PKK/PKZ), numer profilu i kategoria, wybór WORD |
| 2 | `Person` | Termin | rodzaj egzaminu, data „od”, wybór godziny z dostępnych |
| 3 | `Image` | Język egzaminu i pojazd OSK | język egzaminu, opcjonalnie pojazd OSK |
| 4 | `Summary` | Podsumowanie | „Podsumowanie wstępnej rezerwacji” — zatwierdzenie danych |
| 5 | `Confirmation` | Potwierdzenie | potwierdzenie rezerwacji (SSE) → status `PlaceReserved` |
| 6 | `Payment` | Płatność | „Podsumowanie opłat za egzamin”, przekierowanie do bramki płatności |

Przycisk w menu: „Zarezerwuj termin egzaminu” → `routerLink: /reservation`.

### 6.4. API backendu (używane przez frontend)

Bazowe adresy z `GET /assets/config.json`. Wywołania wymagają zalogowania (sprawdzone dla `dict/words` — bez sesji 401;
pozostałe nie były wywoływane).

| Cel | Wywołanie |
|---|---|
| profile PKK do rezerwacji | `GET /bknd/status/api/v1/pkk/get_profiles_for_reservation` |
| słownik ośrodków WORD | `GET /bknd/config/api/v1/dict/words` |
| terminy w jednym WORD | `POST /bknd/exam/api/v1/Schedules/user/OneCenterExam` |
| terminy w wielu WORD | `POST /bknd/exam/api/v1/Schedules/user/MultipleCentersExams` |
| utworzenie rezerwacji | `POST /bknd/exam/api/v1/Reservations/create` |
| potwierdzenie rezerwacji | `/bknd/exam/api/v1/Reservations/confirm/{id}` (SSE) |
| rezerwacje użytkownika | `GET /bknd/exam/api/v1/Reservations` |
| szczegóły / status rezerwacji | `GET /bknd/exam/api/v1/Reservations/{id}`, `.../{id}/state` |

Zapytanie o terminy: `{ startDate, organizationId, category, profileNumber, profileType }`.
Odpowiedź (wiele WORD): lista `{ wordId, wordName, examCollectionForDay: [{ date, examCollections: [...] }] }`.

### 6.5. Statusy rezerwacji

| Status | Etykieta w UI |
|---|---|
| `Created` | W trakcie realizacji |
| `PlaceReserved` | Wstępna rezerwacja |
| `PaymentRequested` | Oczekuje na płatność |
| `PaymentConfirmed` | Opłacona |
| `SignupRequest` | Oczekuje na potwierdzenie |
| `SignupConfirmed` | Potwierdzona |
| `CancellationRequest` | Prośba o anulowanie |
| `Cancelled` | Anulowana |
| `Closed` | Zrealizowany |

Frontend traktuje `PlaceReserved` / `PaymentRequested` / `PaymentConfirmed` jako udane potwierdzenie rezerwacji.

### 6.6. Mechanizmy anty-botowe

Sprawdzone bez logowania (nagłówki HTTP, publiczny kod frontendu):

| Mechanizm | Wynik | Znaczenie dla aplikacji |
|---|---|---|
| WAF / ochrona CDN (Cloudflare, Akamai, Imperva, F5…) | **nie wykryto** — brak charakterystycznych nagłówków i ciasteczek; zapytanie z UA `python-requests` dostaje 200, API bez sesji zwraca czyste 401 (bez strony z wyzwaniem) | czysty klient HTTP prawdopodobnie by działał |
| CAPTCHA (reCAPTCHA, hCaptcha, Turnstile…) | **nie wykryto** w kodzie frontendu | — |
| **Rate limiting** | **jest** — **10 zapytań / 3600 s na endpoint** (zweryfikowane po zalogowaniu, 6.7.4); 429 + `X-RateLimit-Reset`, komunikat „Limit zapytań został przekroczony” | **kluczowe ograniczenie** — sekcja 3, 2.7 |
| **Blokada wielu kart** (`tab-guard.js`) | **jest** — `BroadcastChannel`: druga karta aplikacji w tej samej przeglądarce jest przekierowywana na „Aplikacja jest już otwarta” | działać w jednej karcie |
| Uwierzytelnienie | JWT w ciasteczku `__Secure-PUDOJT` (`SameSite=Strict`), bez nagłówka `Authorization`; odświeżanie `GET /bknd/auth/api/v1/jwt/refresh`; 401/403 → wylogowanie | API wymaga ciasteczek z zalogowanej przeglądarki |
| XSRF | frontend nie wysyła nagłówka XSRF; zapytania z samymi ciasteczkami działają (zweryfikowane, 6.7.3) | brak wymagań |
| Detekcja zachowań po stronie serwera | **nie da się sprawdzić** bez logowania | ryzyko pozostaje |

**Wniosek:** brak twardych zabezpieczeń anty-botowych po stronie klienta; główne ograniczenia to limit zapytań
i jedna karta. Czysty klient HTTP bez przeglądarki jest technicznie możliwy (ciasteczka przeniesione z sesji
przeglądarki), ale:

- logowanie przez mObywatel i tak wymaga przeglądarki,
- zapytania z wnętrza przeglądarki są nieodróżnialne od frontendu (odcisk TLS, nagłówki, ciasteczka, odświeżanie JWT robi sam frontend),
- zysk z odejścia od przeglądarki jest niewielki.

Rekomendacja: **podejście hybrydowe** — API wołane z kontekstu zalogowanej strony w Playwright (2.7).

### 6.7. Rozpoznanie po zalogowaniu (2026-09-14)

Wspólny przebieg: widoczna przeglądarka (Playwright), logowanie QR przez użytkownika, przejście do kroku „Termin”.
Zabezpieczenie: wywołania `Reservations/create|confirm|reschedule|cancel` i `payments/init` były **blokowane**
na poziomie przeglądarki — żadne nie zostało wywołane. Niczego nie zarezerwowano.

#### 6.7.1. Logowanie i sesja

- Ścieżka potwierdzona: `/login` → „login.gov.pl” → `login.gov.pl` → „Aplikacja mObywatel” →
  `login.mobywatel.gov.pl` (QR) → `info-kierowca.pl/logged` → `/cases` („Lista moich spraw”).
- Po zalogowaniu w nagłówku strony licznik sesji „Pozostało 10 minut w sesji” (odnawiany aktywnością).
- Ciasteczka wysyłane do API: `__Host-Http-PUDO-DeviceId`, `__Secure-PUDOJT`, `__Secure-PUDOJTMD`
  (+ `CookieScriptConsent`). Brak nagłówka `Authorization` i XSRF.

#### 6.7.2. UI kroków 1–2

**Krok 1 „Profil i WORD”:**

| Element | Selektor / typ | Uwagi |
|---|---|---|
| Rodzaj profilu | `mat-radio-button` „PKK - Profil kandydata na kierowcę (PKK)” | |
| Numer profilu | `mtx-select#profileNumber` (lista: `[role=option]`) | jedna pozycja w formacie `<numer> — B` |
| Kategoria | `mtx-select#category` | uzupełniana automatycznie, `aria-disabled=true` |
| Tryb | `mat-radio-button` „Pokaż tylko najbliższe terminy dla ośrodków WORD w okolicy” / „Wybierz ośrodek WORD i pokaż wszystkie terminy egzaminów” | |
| Ośrodek | `mtx-select#word` (`formcontrolname=wordId`, wyszukiwanie w `#word-input`) + lista radio 5 najbliższych ośrodków z odległością | |
| Dalej | `button` „Zapisz i przejdź dalej” | przycisk o tej nazwie istnieje w każdym kroku — klikać **widoczny** |

**Krok 2 „Termin”:**

| Element | Selektor / typ | Uwagi |
|---|---|---|
| Rodzaj egzaminu | `mat-radio-button` „Egzamin teoretyczny” / „Egzamin praktyczny” / „Egzamin łączony” / „Wyświetl wszystkie typy egzaminu” | domyślnie „wszystkie” |
| Data rozpoczęcia | `input#startDate` (datepicker, `DD/MM/RRRR`) | domyślnie dziś + 2 dni |
| Dni | `mat-expansion-panel.day` z nagłówkiem `DD/MM/RRRR` | rozwijane kliknięciem |
| Termin | `app-timetable-row-exam` → `mat-checkbox.as-radio` (godzina, liczba wolnych miejsc, cena) | zaznaczenie = wybór terminu |
| Potwierdzenie terminu | okno dialogowe „Potwierdź wybrany egzamin” (rodzaj egzaminu, kategoria, data i godzina, cena), przyciski „Anuluj” / „Potwierdź i przejdź dalej” | otwiera się **od razu po zaznaczeniu terminu** i blokuje resztę strony (zweryfikowane 14.09 23:21) |
| Nawigacja | „Poprzedni krok” / „Zapisz i przejdź dalej” | |

W trybie „najbliższe terminy” krok 2 pokazuje karty `app-timetable-exam-card` — po jednym najbliższym terminie
każdego typu egzaminu na ośrodek.

**Kroki 3–4** (dry run 14.09 23:22): po potwierdzeniu terminu formularz przechodzi przez „Język egzaminu i pojazd OSK”
(radio „Polski”; dane pojazdu OSK pominięte) do kroku **„Podsumowanie”** — „Podsumowanie wstępnej rezerwacji” z sekcjami
„Dane PKK” (numer PKK, kategoria), „Szczegóły egzaminu” (WORD, rodzaj egzaminu, kategoria, data i godzina, miejsce,
dodatkowe informacje, cena) i „Pozostałe informacje” (język egzaminu: Polski, czy pojazd OSK: NIE). Podsumowanie
**nie ma zgód do zaznaczenia**; przyciski „Poprzedni krok” / „Zapisz i przejdź dalej” (zweryfikowane 14.09 23:24).
Do tego momentu frontend **nie wywołał** `Reservations/create` ani `Reservations/confirm` (w dry run są blokowane
i żadne nie zostało zgłoszone) — rezerwacja powstaje dopiero po zatwierdzeniu podsumowania.

#### 6.7.3. API — potwierdzone zapytania i odpowiedzi

Wywołania `fetch` z kontekstu zalogowanej strony działają (200, ~300 ms) — podejście hybrydowe potwierdzone.

| Endpoint | Zapytanie | Odpowiedź |
|---|---|---|
| `GET /bknd/status/api/v1/pkk/get_profiles_for_reservation` | — | lista profili: `pkkNumber`, `categoryName`, `profileType`, `isCoursePassed`, dane osobowe |
| `GET /bknd/config/api/v1/dict/words` | — | 91 ośrodków: `id`, `name`, `location`, adres, `latitude`, `longitude`, `isActive`, `canReschedule` |
| `POST /bknd/exam/api/v1/Schedules/user/MultipleCentersExams` | `{startDate: "RRRR-MM-DD", organizationId: [ids], category: 5, profileNumber, profileType: "Pkk"}` — **`organizationId` musi zawierać dokładnie 5 ośrodków** (dowolnych; `[26, 25]` → 400 „Exactly 5 exam centers must be provided when searching for the fastest terms”, `[26, 25, 1, 2, 3]` → 200 — zweryfikowane 14.09 23:25). Aplikacja dopełnia listę innymi ośrodkami i odrzuca ich wyniki | lista per ośrodek `{wordId, wordName, examCollectionForDay: [wpis]}` — tylko **najbliższy** termin każdego typu |
| `POST /bknd/exam/api/v1/Schedules/user/OneCenterExam` | jak wyżej, **`organizationId` musi być listą z dokładnie jednym ośrodkiem** (`[26]`; liczba → 400 `InvalidRequestBody`; `[26, 25]` → 400 — zweryfikowane 14.09 23:20) | `{startDatePointerForCalendar, examCollectionForDay: [{date, examCollections: [wpis]}]}` — **wszystkie** terminy (~2,5 miesiąca) |
| `GET /bknd/exam/api/v1/Reservations` | — | lista rezerwacji użytkownika (pola niżej) |

**Wpis terminu** (`examCollections[]`):
`practiceId`, `practiceDateTime` (`RRRR-MM-DDTGG:MM:SS`, czas lokalny), `theoryId`, `theoryDateTime`,
`examType` (`Practice` / `Theoretical`), `placePracticeAmount`, `placeTheoryAmount`, `amount` (cena),
`category`, `organizationId`, `organizationName`, `additionalInfo`, `oskCarEnabled`, `firstAvailable`.

**Rezerwacja** (`Reservations[]`): `id`, `reservationDate`, `practiceExamDate`, `practiceExamTime`, `category`,
`status`, `paymentStatus`, `canReschedule`, `examType`, `language`, `profileType`, `profileNumber`, `price`,
`organizationId`, `additionalInfo`, `cancellationReason`.

**Identyfikatory ośrodków:** WORD Warszawa M/E Bemowo = **26**, WORD Warszawa M/E Odlewnicza = **25**.
Kategoria B = **5**.

#### 6.7.4. Limit zapytań — pomiar

Nagłówki na każdej odpowiedzi API terminów: `x-ratelimit-limit: 10`, `x-ratelimit-remaining`, `x-ratelimit-reset`.

- `reset − date` = **3600 s** przy pierwszym zapytaniu → **10 zapytań na godzinę**, okno stałe (nie przesuwne).
- **Osobny licznik na endpoint** (`MultipleCentersExams` i `OneCenterExam` miały różne `reset` i `remaining`).
- Odpowiedzi 400 też zużywają limit.
- Przejście flow w UI zużywa zapytanie (wejście w krok „Termin” wywołuje API terminów).

#### 6.7.5. Obserwacje z danych (14.09.2026, orientacyjnie)

- Bemowo, egzamin praktyczny: sloty o **07:00, 07:50, 08:40, 09:30, 10:20, 11:30, 12:20, 13:10, 14:00**;
  pierwszy wolny termin 21.10, pierwszy w przedziale 10–15 — 22.10; terminy do 30.11.
- Odlewnicza, egzamin praktyczny: najbliższy termin 15.10 06:00.
- W oknie 14 dni (2.6) nie było w tym momencie żadnego terminu praktycznego — aplikacja będzie głównie
  czekać na zwolnione miejsca.
- Na koncie widoczne rezerwacje „Anulowana” z powodem „Brak miejsc na wybranym egzaminie”.

#### 6.7.6. Rezerwacja testowa (2026-09-14 23:45)

- Termin testowy: WORD Warszawa M/E Bemowo, 30.11.2026 14:00 (`--test-reservation`).
- Kroki 1–4 przeszły; po zatwierdzeniu „Podsumowania” serwis pokazał baner:
  „Rezerwacja nie powiodła się - Profil Kandydata na Kierowcę (PKK) znajduje się w Wojewódzkim Ośrodku Ruchu
  Drogowego (WORD), innym niż podany w rezerwacji. Skontaktuj się z WORD w celu aktualizacji profilu.”
- Wniosek: **rezerwacja jest możliwa tylko w WORD, w którym znajduje się PKK** — M/E Bemowo i M/E Odlewnicza
  są osobnymi ośrodkami (`organizationId` 26 i 25), a dotychczasowe rezerwacje na koncie były w Odlewniczej (25).
- Weryfikacja na liście rezerwacji: **żadna nowa rezerwacja nie powstała** (nadal 10, wszystkie w Odlewniczej, anulowane).
- Jedna z wcześniejszych rezerwacji ma powód anulowania „Użytkownik nie kontynuował procesu rezerwacji. Minął
  maksymalny czas na rozpoczęcie płatności (30 minut)” — potwierdza 30-minutowe trzymanie terminu (2.3).
- Kroki 5–6 („Potwierdzenie”, „Płatność”) nadal **niezweryfikowane**.
