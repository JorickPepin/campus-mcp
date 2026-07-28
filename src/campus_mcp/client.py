"""Async HTTP client for the Campus Coach API with transparent token refresh."""

import asyncio
import ssl
from typing import Any

import aiohttp
import certifi

BASE_URL = "https://api.campus.coach"


class CampusAuthError(Exception):
    """Raised when authentication against the Campus API definitively fails."""


class CampusClient:
    """Wraps aiohttp.ClientSession to handle Bearer auth and 401 replay.

    No preemptive expiry checks: requests are sent with the current token and
    replayed once after a refresh if the API answers 401.
    """

    def __init__(self, email: str, password: str) -> None:
        self._email = email
        self._password = password
        self._token: str | None = None
        self._refresh_token: str | None = None
        self._session: aiohttp.ClientSession | None = None
        self._auth_lock = asyncio.Lock()

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        session = self._ensure_session()
        if self._token is None:
            async with self._auth_lock:
                if self._token is None:
                    await self._login(session)

        token_used = self._token
        async with session.get(
            f"{BASE_URL}{path}", params=params, headers=self._headers()
        ) as resp:
            if resp.status != 401:
                resp.raise_for_status()
                return await resp.json()

        async with self._auth_lock:
            # Another request may have refreshed the token while we waited.
            if self._token == token_used:
                await self._refresh(session)

        async with session.get(
            f"{BASE_URL}{path}", params=params, headers=self._headers()
        ) as resp:
            if resp.status == 401:
                raise CampusAuthError(
                    f"Still unauthorized on {path} after token refresh"
                )
            resp.raise_for_status()
            return await resp.json()

    def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            # Some Python installs ship no OpenSSL CA bundle: use certifi's.
            connector = aiohttp.TCPConnector(
                ssl=ssl.create_default_context(cafile=certifi.where())
            )
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    async def _login(self, session: aiohttp.ClientSession) -> None:
        async with session.post(
            f"{BASE_URL}/account/login",
            json={"email": self._email, "password": self._password},
        ) as resp:
            if resp.status >= 400:
                raise CampusAuthError(
                    f"Login failed ({resp.status}): check CAMPUS_EMAIL/CAMPUS_PASSWORD"
                )
            self._store_tokens(await resp.json())

    async def _refresh(self, session: aiohttp.ClientSession) -> None:
        async with session.put(
            f"{BASE_URL}/account/refresh-token/{self._refresh_token}"
        ) as resp:
            if resp.status >= 400:
                # Refresh token expired or revoked: fall back to a full login.
                await self._login(session)
                return
            self._store_tokens(await resp.json())

    def _store_tokens(self, payload: dict[str, Any]) -> None:
        self._token = payload["token"]
        self._refresh_token = payload["refreshToken"]
