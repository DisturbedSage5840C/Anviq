"""Set up the Evolution WhatsApp channel on the demo machine. Standard library only.

    set -a; . infra/demo.env; set +a
    python3 infra/demo/evolution_setup.py setup               # create the instance, set the webhook
    python3 infra/demo/evolution_setup.py pair 91XXXXXXXXXX   # print the code to type on the phone
    python3 infra/demo/evolution_setup.py status              # open = paired, close = pair again

It prints a status line or the pairing code and nothing else: Evolution's create response holds
the instance's own token, so response bodies are never shown.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

BASE_URL = os.environ.get("EVOLUTION_LOCAL_URL", "http://127.0.0.1:8081")
# Evolution posts to the API over the compose network, so this never leaves the machine.
WEBHOOK_URL = os.environ.get(
    "EVOLUTION_WEBHOOK_TARGET", "http://api:8080/webhook/evolution"
)
TIMEOUT_S = 30
ALREADY_EXISTS = (403, 409)
BAD_API_KEY = 401
# Country code plus a national number; 10 digits is a bare national number with no country code.
MIN_NUMBER_DIGITS = 11


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(
            f"{name} is not set. Load infra/demo.env first (see the top of this file)."
        )
    return value


def _call(
    method: str, path: str, api_key: str, body: dict[str, Any] | None = None
) -> tuple[int, dict[str, Any]]:
    status, parsed = _request(method, path, api_key, body)
    if status == BAD_API_KEY:
        sys.exit(
            "Evolution rejected EVOLUTION_API_KEY (HTTP 401). Is it the key the stack started with?"
        )
    return status, parsed


def _request(
    method: str, path: str, api_key: str, body: dict[str, Any] | None
) -> tuple[int, dict[str, Any]]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(  # noqa: S310 - fixed local URL
        f"{BASE_URL}{path}",
        data=data,
        method=method,
        headers={"apikey": api_key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310
            return response.status, _json_or_empty(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, _json_or_empty(exc.read())
    except urllib.error.URLError as exc:
        sys.exit(
            f"Cannot reach Evolution at {BASE_URL}: {exc.reason}. "
            "Is the stack up with --profile evolution?"
        )


def _json_or_empty(raw: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def setup(api_key: str, instance: str, secret: str) -> None:
    created = {
        "instanceName": instance,
        "integration": "WHATSAPP-BAILEYS",
        "qrcode": False,
    }
    status, _ = _call("POST", "/instance/create", api_key, created)
    if status >= 400 and status not in ALREADY_EXISTS:
        sys.exit(f"Creating the instance failed (HTTP {status}).")
    print("instance ready" if status < 400 else "instance already exists")

    webhook = {
        "enabled": True,
        "url": WEBHOOK_URL,
        "webhookByEvents": False,
        "webhookBase64": False,
        "events": ["MESSAGES_UPSERT"],
        "headers": {"X-Anviq-Webhook-Secret": secret},
    }
    status, _ = _call("POST", f"/webhook/set/{instance}", api_key, {"webhook": webhook})
    if status >= 400:
        sys.exit(f"Setting the webhook failed (HTTP {status}).")
    print("webhook set")


def pair(api_key: str, instance: str, number: str) -> None:
    digits = "".join(ch for ch in number if ch.isdigit())
    if len(digits) < MIN_NUMBER_DIGITS:
        sys.exit("Give the full number with country code, e.g. 91XXXXXXXXXX.")
    status, body = _call(
        "GET", f"/instance/connect/{instance}?number={digits}", api_key
    )
    code = body.get("pairingCode")
    if status >= 400 or not isinstance(code, str) or not code:
        sys.exit(
            f"No pairing code returned (HTTP {status}). Run `setup` first, or `status`."
        )
    print(f"Pairing code: {code}")
    print("On the phone: WhatsApp > Settings > Linked devices > Link a device,")
    print("then choose 'Link with phone number instead' and type the code.")


def status(api_key: str, instance: str) -> None:
    code, body = _call("GET", f"/instance/connectionState/{instance}", api_key)
    details = body.get("instance")
    state = details.get("state") if isinstance(details, dict) else None
    print(f"connection: {state or 'unknown'} (HTTP {code})")


def main(argv: list[str]) -> None:
    command = argv[1] if len(argv) > 1 else ""
    api_key = _required("EVOLUTION_API_KEY")
    instance = _required("EVOLUTION_INSTANCE")
    if command == "setup":
        setup(api_key, instance, _required("EVOLUTION_WEBHOOK_SECRET"))
    elif command == "pair" and len(argv) == 3:
        pair(api_key, instance, argv[2])
    elif command == "status":
        status(api_key, instance)
    else:
        sys.exit(
            "usage: evolution_setup.py setup | pair <number-with-country-code> | status"
        )


if __name__ == "__main__":
    main(sys.argv)
