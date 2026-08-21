"""Coverage for the 401 -> refresh -> replay path.

This path only runs once an access token has expired, which takes 15 minutes of
uptime -- long enough that a refresh sending no Authorization header shipped and
went unnoticed. Everything here exists so that cannot happen twice.
"""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from campus_mcp.auth import TokenStore
from campus_mcp.client import CampusAuthError, CampusClient


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("campus_mcp.client.REFRESH_RETRY_DELAY", 0)


@pytest.fixture
def store(tmp_path: Path) -> TokenStore:
    return TokenStore(path=tmp_path / "campus" / "tokens.json")


class FakeResponse:
    def __init__(self, status: int, payload: dict[str, Any] | None = None) -> None:
        self.status = status
        self._payload = payload or {}

    async def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise AssertionError(f"raise_for_status() called on {self.status}")

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


class FakeSession:
    """Serves canned responses per HTTP method and records what was sent.

    aiohttp's session.get()/put()/post() return an async context manager rather
    than a coroutine, so these are plain methods.
    """

    def __init__(self, **queues: list[FakeResponse]) -> None:
        self._queues = queues
        self.calls: list[tuple[str, str, dict[str, str] | None]] = []
        self.closed = False

    def _serve(
        self, method: str, url: str, headers: dict[str, str] | None
    ) -> FakeResponse:
        self.calls.append((method, url, headers))
        queue = self._queues.get(method, [])
        if not queue:
            raise AssertionError(f"unexpected {method} {url}")
        return queue.pop(0)

    def get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> FakeResponse:
        return self._serve("GET", url, headers)

    def put(self, url: str, headers: dict[str, str] | None = None) -> FakeResponse:
        return self._serve("PUT", url, headers)

    def post(self, url: str, json: dict[str, Any] | None = None) -> FakeResponse:
        return self._serve("POST", url, None)

    async def close(self) -> None:
        self.closed = True

    def methods(self) -> list[str]:
        return [method for method, _, _ in self.calls]

    def only(self, method: str) -> list[tuple[str, str, dict[str, str] | None]]:
        return [call for call in self.calls if call[0] == method]


def make_client(session: FakeSession, **kwargs: Any) -> CampusClient:
    client = CampusClient(**kwargs)
    client._session = session  # type: ignore[assignment]
    client._token = "expired"
    client._refresh_token = "refresh-abc"
    return client


def rotated(token: str = "fresh") -> FakeResponse:
    # The refresh token comes back unchanged: Campus does not rotate it.
    return FakeResponse(200, {"token": token, "refreshToken": "refresh-abc"})


def test_refresh_sends_the_bearer_header() -> None:
    # The bug this whole module guards against. Campus answers 401 MissingToken
    # to a bare PUT, which reads exactly like a revoked refresh token, so the
    # server would fall over 15 minutes after every start with no clue why.
    session = FakeSession(
        GET=[FakeResponse(401), FakeResponse(200, {"ok": True})],
        PUT=[rotated()],
    )
    client = make_client(session)

    assert asyncio.run(client.get("/smart-training")) == {"ok": True}

    (_, url, headers) = session.only("PUT")[0]
    assert url.endswith("/account/refresh-token/refresh-abc")
    # Carrying the *expired* token is correct: Campus checks the signature, not
    # the expiry. Asserting the value keeps that non-obvious fact pinned down.
    assert headers == {"Authorization": "Bearer expired"}


def test_replays_the_original_request_with_the_new_token() -> None:
    session = FakeSession(
        GET=[FakeResponse(401), FakeResponse(200, {"ok": True})],
        PUT=[rotated()],
    )
    client = make_client(session)

    asyncio.run(client.get("/smart-training"))

    first, second = session.only("GET")
    assert first[2] == {"Authorization": "Bearer expired"}
    assert second[2] == {"Authorization": "Bearer fresh"}


def test_transient_404_is_retried(store: TokenStore) -> None:
    # Two processes refreshing in the same second: one wins, the other gets a
    # 404 that means nothing.
    store.save("expired", "refresh-abc")
    session = FakeSession(
        GET=[FakeResponse(401), FakeResponse(200, {"ok": True})],
        PUT=[FakeResponse(404), rotated()],
    )
    client = make_client(session, token_store=store)

    assert asyncio.run(client.get("/smart-training")) == {"ok": True}
    assert len(session.only("PUT")) == 2


def test_a_sibling_refresh_is_adopted_without_asking_the_api(
    store: TokenStore,
) -> None:
    # The file already holds a working access token, so there is nothing to ask.
    store.save("fresh-from-sibling", "refresh-abc")
    session = FakeSession(
        GET=[FakeResponse(401), FakeResponse(200, {"ok": True})],
        PUT=[FakeResponse(404)],
    )
    client = make_client(session, token_store=store)

    asyncio.run(client.get("/smart-training"))

    assert len(session.only("PUT")) == 1
    assert session.only("GET")[1][2] == {"Authorization": "Bearer fresh-from-sibling"}


def test_credentials_skip_the_retry_and_log_in() -> None:
    # A login is cheaper and more certain than a second rotation attempt.
    session = FakeSession(
        GET=[FakeResponse(401), FakeResponse(200, {"ok": True})],
        PUT=[FakeResponse(404)],
        POST=[rotated("from-login")],
    )
    client = make_client(session, email="a@b.c", password="pw")

    asyncio.run(client.get("/smart-training"))

    assert session.methods() == ["GET", "PUT", "POST", "GET"]
    assert session.only("GET")[1][2] == {"Authorization": "Bearer from-login"}


def test_persistent_failure_without_credentials_raises(store: TokenStore) -> None:
    store.save("expired", "refresh-abc")
    session = FakeSession(
        GET=[FakeResponse(401)],
        PUT=[FakeResponse(401), FakeResponse(401)],
    )
    client = make_client(session, token_store=store)

    with pytest.raises(CampusAuthError, match="campus-mcp-auth"):
        asyncio.run(client.get("/smart-training"))


def test_a_successful_refresh_is_persisted(store: TokenStore) -> None:
    store.save("expired", "refresh-abc")
    session = FakeSession(
        GET=[FakeResponse(401), FakeResponse(200, {"ok": True})],
        PUT=[rotated()],
    )
    client = make_client(session, token_store=store)

    asyncio.run(client.get("/smart-training"))

    assert store.load() == {"token": "fresh", "refreshToken": "refresh-abc"}
