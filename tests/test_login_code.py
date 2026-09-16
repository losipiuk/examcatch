import base64
from datetime import datetime, timedelta

from examcatch.browser import parse_login_code
from examcatch.models import WARSAW

RECEIVED_AT = datetime(2026, 9, 16, 14, 0, 0, tzinfo=WARSAW)
PNG = b"\x89PNG\r\n\x1a\nfake image"
IMAGE_URI = "data:image/png;base64," + base64.b64encode(PNG).decode()
# Same shape as the service's code; the UUID and host are made up.
TOKEN = "8;D;1;;;9216;;00000000-0000-4000-8000-000000000000;1789559777;1789560077;prod-mlogin-app-x1;0;3;;"


def test_parses_image_text_and_validity():
    code = parse_login_code(TOKEN, IMAGE_URI, RECEIVED_AT)

    assert code.text == TOKEN
    assert code.image_png == PNG
    assert code.expires_at == RECEIVED_AT + timedelta(seconds=300)


def test_defaults_to_five_minutes_without_timestamps():
    code = parse_login_code("8;D;1;;;9216;;x;;;host;0;3;;", IMAGE_URI, RECEIVED_AT)

    assert code.expires_at == RECEIVED_AT + timedelta(minutes=5)


def test_missing_or_invalid_image_is_skipped():
    assert parse_login_code(TOKEN, None, RECEIVED_AT).image_png is None
    assert parse_login_code(TOKEN, "data:image/png;base64,***", RECEIVED_AT).image_png is None
    assert parse_login_code(TOKEN, "https://example.com/qr.png", RECEIVED_AT).image_png is None
