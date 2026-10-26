"""The demo stack's privacy and exposure promises, written in comments, checked as data."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

INFRA = Path(__file__).resolve().parents[3] / "infra"
LOCAL_ONLY = "127.0.0.1:"
EVOLUTION_NETWORK = "evolution"
SECRETS_COMPOSE_MUST_DEMAND = (
    "APP_DB_PASSWORD",
    "WA_VERIFY_TOKEN",
    "WA_APP_SECRET",
    "ANTHROPIC_API_KEY",
    "FIELD_KEY",
    "PHONE_PEPPER",
)


def _load(name: str) -> dict[str, Any]:
    loaded = yaml.safe_load((INFRA / name).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


@pytest.fixture(scope="module")
def services() -> dict[str, dict[str, Any]]:
    return _load("docker-compose.demo.yml")["services"]


@pytest.fixture(scope="module")
def caddyfile() -> str:
    return (INFRA / "demo" / "Caddyfile").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["docker-compose.yml", "docker-compose.demo.yml"])
def test_every_compose_file_names_its_services_and_images_by_a_pinned_tag(name: str):
    for service, spec in _load(name)["services"].items():
        image = spec.get("image")
        if image is None or "build" in spec:
            continue
        assert ":" in image and not image.endswith(":latest"), f"{service} uses {image}"


def test_only_caddy_publishes_ports_to_the_world(services: dict[str, dict[str, Any]]):
    for name, spec in services.items():
        for port in spec.get("ports", []):
            assert name == "caddy" or str(port).startswith(LOCAL_ONLY), f"{name} exposes {port}"


def test_caddy_serves_only_http_and_https(services: dict[str, dict[str, Any]]):
    assert set(services["caddy"]["ports"]) == {"80:80", "443:443"}


@pytest.mark.parametrize("name", ["postgres", "redis"])
def test_the_teacher_data_stores_publish_no_ports(services: dict[str, dict[str, Any]], name: str):
    assert "ports" not in services[name]


def test_the_third_party_whatsapp_bridge_cannot_reach_the_teacher_data(
    services: dict[str, dict[str, Any]],
):
    on_evolution = {
        name for name, spec in services.items() if EVOLUTION_NETWORK in spec.get("networks", [])
    }

    assert on_evolution == {"api", "worker", "evolution", "evolution-db"}
    for name in ("evolution", "evolution-db"):
        assert services[name]["networks"] == [EVOLUTION_NETWORK]


def test_the_bridge_and_its_database_start_only_when_the_evolution_profile_is_on(
    services: dict[str, dict[str, Any]],
):
    for name in ("evolution", "evolution-db", "evolution-guard"):
        assert services[name]["profiles"] == ["evolution"]


def test_the_app_runs_as_the_restricted_database_role_and_only_migrations_use_the_owner(
    services: dict[str, dict[str, Any]],
):
    def database_url(name: str) -> str:
        env = services[name]["environment"]
        return next(item for item in env if item.startswith("DATABASE_URL="))

    assert "//app_rw:" in database_url("api")
    assert "//app_rw:" in database_url("worker")
    assert "//anviq:" in database_url("migrate")


@pytest.mark.parametrize("secret", SECRETS_COMPOSE_MUST_DEMAND)
def test_a_missing_required_secret_stops_the_stack_instead_of_starting_it_blank(
    services: dict[str, dict[str, Any]], secret: str
):
    env = services["api"]["environment"]

    assert any(re.search(rf"\$\{{{secret}:\?[^}}]+\}}", item) for item in env), secret


def test_the_worker_and_api_get_the_same_settings(services: dict[str, dict[str, Any]]):
    assert services["worker"]["environment"] == services["api"]["environment"]


def test_caddy_mounts_its_config_and_the_web_room_read_only(services: dict[str, dict[str, Any]]):
    mounts = [v for v in services["caddy"]["volumes"] if "caddydata" not in v]

    assert mounts and all(v.endswith(":ro") for v in mounts)


def test_the_public_site_never_forwards_the_bridge_webhook_to_the_api(caddyfile: str):
    assert re.search(
        r"@evolution_webhook path /webhook/evolution /webhook/evolution/\*\s+"
        r"handle @evolution_webhook \{\s+respond 404",
        caddyfile,
    )


def test_every_response_carries_the_security_headers(caddyfile: str):
    header_block = caddyfile.split("header {", 1)[1].split("}", 1)[0]

    assert 'Strict-Transport-Security "max-age=86400"' in header_block
    assert 'X-Content-Type-Options "nosniff"' in header_block
    assert 'Referrer-Policy "no-referrer"' in header_block
    assert "camera=()" in header_block
    assert "geolocation=()" in header_block
    assert "microphone=(self)" in header_block


def test_the_web_room_page_may_only_talk_to_its_own_origin(caddyfile: str):
    policy = re.search(r'Content-Security-Policy "([^"]+)"', caddyfile)
    assert policy is not None
    directives = dict(part.strip().split(" ", 1) for part in policy.group(1).split(";"))

    assert directives["default-src"] == "'none'"
    assert directives["connect-src"] == "'self'"
    assert directives["script-src"] == "'self'"
    assert directives["frame-ancestors"] == "'none'"
    assert "unsafe-inline" not in policy.group(1) and "unsafe-eval" not in policy.group(1)


def test_everything_else_goes_to_the_api_over_the_internal_network(caddyfile: str):
    assert re.search(r"handle \{\s+reverse_proxy api:8080\s+\}", caddyfile)
