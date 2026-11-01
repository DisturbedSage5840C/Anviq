import httpx
import pytest

from app.core.ask.fetch import USER_AGENT, FetchError, HttpxFetcher, TransientFetchError


def _fetcher(handler) -> HttpxFetcher:
    return HttpxFetcher(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_returns_the_body_of_a_successful_response():
    fetcher = _fetcher(lambda request: httpx.Response(200, content=b"%PDF-1.7"))

    assert fetcher.fetch("https://x/a.pdf") == b"%PDF-1.7"


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_server_trouble_is_transient(status):
    fetcher = _fetcher(lambda request: httpx.Response(status))

    with pytest.raises(TransientFetchError):
        fetcher.fetch("https://x/a.pdf")


@pytest.mark.parametrize("status", [403, 404])
def test_client_errors_are_permanent(status):
    fetcher = _fetcher(lambda request: httpx.Response(status))

    with pytest.raises(FetchError) as caught:
        fetcher.fetch("https://x/a.pdf")

    assert not isinstance(caught.value, TransientFetchError)


def test_a_reset_connection_is_transient():
    def reset(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("Connection reset by peer")

    with pytest.raises(TransientFetchError, match="ReadError"):
        _fetcher(reset).fetch("https://x/a.pdf")


def test_the_default_client_sends_a_neutral_user_agent():
    fetcher = HttpxFetcher()
    try:
        agent = fetcher._client.headers["User-Agent"]
    finally:
        fetcher.close()

    assert agent == USER_AGENT
    assert "@" not in agent


def test_system_trust_context_verifies_certificates_and_hostnames():
    import ssl

    from app.core.ask.fetch import system_trust_context

    context = system_trust_context()

    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_the_default_client_verifies_with_the_system_trust_store(monkeypatch):
    sentinel = object()
    seen: dict[str, object] = {}

    class RecordingClient:
        def __init__(self, **kwargs: object) -> None:
            seen.update(kwargs)

    monkeypatch.setattr("app.core.ask.fetch.system_trust_context", lambda: sentinel)
    monkeypatch.setattr("app.core.ask.fetch.httpx.Client", RecordingClient)

    HttpxFetcher()

    assert seen["verify"] is sentinel
    assert seen["follow_redirects"] is True
