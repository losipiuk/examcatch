from examcatch.reservation import WRONG_CENTER_MESSAGE, clean_alert_text


def test_clean_alert_text_drops_icon_words():
    text = (
        "warning\nRezerwacja nie powiodła się - Profil Kandydata na Kierowcę (PKK) znajduje się w Wojewódzkim "
        "Ośrodku Ruchu Drogowego (WORD), innym niż podany w rezerwacji. Skontaktuj się z WORD w celu aktualizacji "
        "profilu.\nclose"
    )

    cleaned = clean_alert_text(text)

    assert cleaned.startswith("Rezerwacja nie powiodła się")
    assert cleaned.endswith("aktualizacji profilu.")
    assert WRONG_CENTER_MESSAGE in cleaned


def test_clean_alert_text_of_icons_only_is_empty():
    assert clean_alert_text("warning close") == ""
