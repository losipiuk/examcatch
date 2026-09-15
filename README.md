# ExamCatch

Watches [info-kierowca.pl](https://info-kierowca.pl) for practical driving exam (category B) slots, reserves the
earliest acceptable one up to the payment step and notifies you by e-mail and WhatsApp. Payment is left to you.
After you pay, it keeps watching and tells you about earlier slots.

The full specification (in Polish) is in [specyfikacja.md](specyfikacja.md).

## Setup

```bash
uv sync
uv run playwright install chromium
cp config.example.yaml config.yaml   # then edit it
```

WhatsApp notifications use [CallMeBot](https://www.callmebot.com/blog/free-api-whatsapp-messages/):
send the activation message from your phone once to get an API key.

Secrets are referenced from `config.yaml` as `${NAME}`; keep them in `.env` (ignored by git) and `source .env`.
Check the channels with:

```bash
uv run examcatch --config config.yaml --test-notifications
```

## Usage

```bash
uv run examcatch --config config.yaml
```

1. A browser window opens. Log in by scanning the QR code with the mObywatel app.
2. ExamCatch checks for slots and, when it finds an acceptable one, fills in the reservation form up to the
   payment step. The slot is held for 30 minutes.
3. Pay in the browser (or in the service's reservation list), then type `paid` and press Enter in the terminal.
   Without the confirmation ExamCatch keeps reminding you and, after 30 minutes, starts searching again.
4. Afterwards it notifies you about every slot earlier than your reservation. Stop it with Ctrl+C.

When the session expires, press Enter in the terminal and scan the QR code again.

Everything printed to the terminal is also appended to `.examcatch/examcatch.log`, including unexpected errors with
their stack trace (configurable under `logging` in `config.yaml`).

### Dry run

```bash
uv run examcatch --config config.yaml --dry-run
```

Logs in, fills in the reservation form for the nearest offered slot (even one not meeting the criteria) up to the
summary step, prints the controls it sees, saves a screenshot and stops. Nothing is submitted; requests that could
create or hold a reservation are blocked in the browser.

### Test reservation

```bash
uv run examcatch --config config.yaml --test-reservation
```

Really reserves the latest offered slot (ignoring the criteria) up to the payment step, sends the "reserved"
notification and exits. Do not pay; the reservation expires after 30 minutes.

## Request limits

The service allows only 10 requests per hour per API endpoint. ExamCatch alternates between the nearest-slot and the
full schedule endpoints, which have separate limits, checking about every 3.5 minutes. Full schedules are skipped
when they cannot contain an acceptable slot, and requests are always kept in reserve for the reservation form.

When someone else takes a slot before ExamCatch can reserve it, their reservation is cancelled after 30 minutes if
they don't pay, so ExamCatch plans extra checks for that moment.

## Development

```bash
uv run pytest
```
