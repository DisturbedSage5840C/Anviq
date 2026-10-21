import json

from tests.conftest import TEST_VERIFY_TOKEN, sign

URL = "/webhook/whatsapp"

TEXT_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "changes": [
                {
                    "value": {
                        "messages": [
                            {
                                "id": "wamid.1",
                                "from": "919999999999",
                                "type": "text",
                                "text": {"body": "Namaste"},
                            }
                        ]
                    }
                }
            ]
        }
    ],
}


def _body(payload: dict) -> bytes:
    return json.dumps(payload).encode()


def test_verify_echoes_challenge_when_token_matches(client):
    response = client.get(
        URL,
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": TEST_VERIFY_TOKEN,
            "hub.challenge": "12345",
        },
    )
    assert response.status_code == 200
    assert response.text == "12345"


def test_verify_rejects_wrong_token(client):
    response = client.get(
        URL,
        params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "1"},
    )
    assert response.status_code == 403


def test_verify_rejects_wrong_mode(client):
    response = client.get(
        URL,
        params={
            "hub.mode": "unsubscribe",
            "hub.verify_token": TEST_VERIFY_TOKEN,
            "hub.challenge": "1",
        },
    )
    assert response.status_code == 403


def test_post_with_valid_signature_is_accepted(client):
    body = _body(TEXT_PAYLOAD)
    response = client.post(URL, content=body, headers={"X-Hub-Signature-256": sign(body)})
    assert response.status_code == 200


def test_post_without_signature_is_rejected(client):
    response = client.post(URL, content=_body(TEXT_PAYLOAD))
    assert response.status_code == 401


def test_post_with_tampered_body_is_rejected(client):
    body = _body(TEXT_PAYLOAD)
    signature = sign(body)
    response = client.post(URL, content=body + b" ", headers={"X-Hub-Signature-256": signature})
    assert response.status_code == 401


def test_post_signed_with_wrong_secret_is_rejected(client):
    body = _body(TEXT_PAYLOAD)
    response = client.post(
        URL, content=body, headers={"X-Hub-Signature-256": sign(body, secret="other")}
    )
    assert response.status_code == 401


def test_post_with_malformed_signature_header_is_rejected(client):
    response = client.post(
        URL, content=_body(TEXT_PAYLOAD), headers={"X-Hub-Signature-256": "not-a-signature"}
    )
    assert response.status_code == 401


def test_post_with_signed_invalid_json_returns_400(client):
    body = b"{not json"
    response = client.post(URL, content=body, headers={"X-Hub-Signature-256": sign(body)})
    assert response.status_code == 400


def test_a_non_ascii_signature_header_is_rejected_not_a_server_error(client):
    response = client.post(
        URL,
        content=_body(TEXT_PAYLOAD),
        headers={"X-Hub-Signature-256": "sha256=é".encode("latin-1")},
    )
    assert response.status_code == 401


def test_verify_rejects_a_non_ascii_token_not_a_server_error(client):
    response = client.get(
        URL,
        params={"hub.mode": "subscribe", "hub.verify_token": "tokén", "hub.challenge": "1"},
    )
    assert response.status_code == 403


def test_a_failed_delivery_is_logged_by_code_without_the_recipient(client, caplog):
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [
                                {
                                    "status": "failed",
                                    "recipient_id": "919999999999",
                                    "errors": [{"code": 131030}],
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    body = _body(payload)

    with caplog.at_level("WARNING", logger="app.api.whatsapp_webhook"):
        response = client.post(URL, content=body, headers={"X-Hub-Signature-256": sign(body)})

    assert response.status_code == 200
    assert "whatsapp delivery failed: code=131030" in caplog.text
    assert "919999999999" not in caplog.text
