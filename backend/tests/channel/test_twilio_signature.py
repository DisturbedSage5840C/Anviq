import pytest

from app.channel.twilio_signature import is_valid_twilio_signature, twilio_signature

# The worked example from Twilio's request-validation docs; also reproduced with
# `openssl dgst -sha1 -hmac 12345 -binary | openssl base64` so the test does not
# just compare the implementation with itself.
TOKEN = "12345"
URL = "https://mycompany.com/myapp.php?foo=1&bar=2"
PARAMS = [
    ("Digits", "1234"),
    ("To", "+18005551212"),
    ("From", "+12349013030"),
    ("Caller", "+12349013030"),
    ("CallSid", "CA1234567890ABCDE"),
]
EXPECTED = "0/KCTR6DLpKmkAf8muzZqo1nDgQ="


def test_signature_matches_the_twilio_documented_example() -> None:
    assert twilio_signature(TOKEN, URL, PARAMS) == EXPECTED


def test_a_correct_signature_is_accepted() -> None:
    assert is_valid_twilio_signature(TOKEN, URL, PARAMS, EXPECTED)


def test_parameter_order_on_the_wire_does_not_matter() -> None:
    assert is_valid_twilio_signature(TOKEN, URL, list(reversed(PARAMS)), EXPECTED)


@pytest.mark.parametrize("signature", [None, "", "not-a-signature", "0/KCTR6DLpKmkAf8muzZqo1nDgQ"])
def test_a_missing_or_wrong_signature_is_rejected(signature: str | None) -> None:
    assert not is_valid_twilio_signature(TOKEN, URL, PARAMS, signature)


def test_a_signature_made_with_another_token_is_rejected() -> None:
    assert not is_valid_twilio_signature("other-token", URL, PARAMS, EXPECTED)


def test_a_tampered_parameter_is_rejected() -> None:
    tampered = [(k, "+19999999999" if k == "From" else v) for k, v in PARAMS]

    assert not is_valid_twilio_signature(TOKEN, URL, tampered, EXPECTED)


def test_a_different_url_is_rejected() -> None:
    assert not is_valid_twilio_signature(TOKEN, "https://evil.example/myapp.php", PARAMS, EXPECTED)


def test_a_repeated_key_sorts_its_values_so_delivery_order_cannot_change_the_result() -> None:
    first = twilio_signature(TOKEN, URL, [("Tag", "b"), ("Tag", "a")])
    second = twilio_signature(TOKEN, URL, [("Tag", "a"), ("Tag", "b")])

    assert first == second


def test_non_ascii_values_are_signed_as_utf8() -> None:
    signature = twilio_signature(TOKEN, URL, [("Body", "नमस्ते")])

    assert is_valid_twilio_signature(TOKEN, URL, [("Body", "नमस्ते")], signature)
    assert not is_valid_twilio_signature(TOKEN, URL, [("Body", "नमस्कार")], signature)


def test_a_non_ascii_signature_header_is_rejected_not_raised() -> None:
    assert not is_valid_twilio_signature(TOKEN, URL, PARAMS, "सही-हस्ताक्षर")
