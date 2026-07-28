import asyncio
import json
import stat
from pathlib import Path

import pytest

from campus_mcp.auth import TokenStore
from campus_mcp.client import CampusAuthError, CampusClient


@pytest.fixture
def store(tmp_path: Path) -> TokenStore:
    return TokenStore(path=tmp_path / "campus" / "tokens.json")


class TestTokenStore:
    def test_round_trip(self, store: TokenStore) -> None:
        store.save("tok", "refresh")
        assert store.load() == {"token": "tok", "refreshToken": "refresh"}

    def test_save_overwrites(self, store: TokenStore) -> None:
        store.save("tok1", "refresh1")
        store.save("tok2", "refresh2")
        assert store.load() == {"token": "tok2", "refreshToken": "refresh2"}

    def test_load_missing_file(self, store: TokenStore) -> None:
        assert store.load() is None

    def test_load_corrupt_file(self, store: TokenStore) -> None:
        store.path.parent.mkdir(parents=True)
        store.path.write_text("not json")
        assert store.load() is None

    def test_load_incomplete_payload(self, store: TokenStore) -> None:
        store.path.parent.mkdir(parents=True)
        store.path.write_text(json.dumps({"token": "tok"}))
        assert store.load() is None

    def test_permissions(self, store: TokenStore) -> None:
        store.save("tok", "refresh")
        assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
        assert stat.S_IMODE(store.path.parent.stat().st_mode) == 0o700

    def test_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CAMPUS_TOKEN_FILE", str(tmp_path / "custom.json"))
        assert TokenStore().path == tmp_path / "custom.json"


class TestClientAuth:
    def test_authenticate_from_store(self, store: TokenStore) -> None:
        store.save("tok", "refresh")
        client = CampusClient(token_store=store)
        asyncio.run(client._authenticate(session=None))
        assert client._token == "tok"
        assert client._refresh_token == "refresh"

    def test_authenticate_without_anything(self) -> None:
        client = CampusClient()
        with pytest.raises(CampusAuthError, match="campus-mcp-auth"):
            asyncio.run(client._authenticate(session=None))

    def test_credentials_win_over_store(
        self, store: TokenStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store.save("stale", "stale")
        client = CampusClient(email="a@b.c", password="pw", token_store=store)
        logged_in = False

        async def fake_login(session: object) -> None:
            nonlocal logged_in
            logged_in = True

        monkeypatch.setattr(client, "_login", fake_login)
        asyncio.run(client._authenticate(session=None))
        assert logged_in

    def test_rotation_persists_to_store(self, store: TokenStore) -> None:
        client = CampusClient(token_store=store)
        client._store_tokens({"token": "new", "refreshToken": "new-refresh"})
        assert store.load() == {"token": "new", "refreshToken": "new-refresh"}

    def test_rotation_without_store_stays_in_memory(self) -> None:
        client = CampusClient(email="a@b.c", password="pw")
        client._store_tokens({"token": "new", "refreshToken": "new-refresh"})
        assert client._token == "new"
