import asyncio

import pytest
from mcp.client import Client

from campus_mcp.server import MAX_CHUNK_MS, _fetch_logged, _fetch_weeks, mcp
from campus_mcp.transform import WEEK_MS


class RecordingClient:
    """Stands in for CampusClient and records every (path, params) it is given."""

    def __init__(self, payload: list[dict] | None = None) -> None:
        self.payload = payload if payload is not None else []
        self.calls: list[tuple[str, dict]] = []

    async def get(self, path: str, params: dict | None = None) -> list[dict]:
        self.calls.append((path, params or {}))
        return self.payload


def test_tools_are_exposed(monkeypatch: pytest.MonkeyPatch) -> None:
    # The lifespan needs credentials or a token file; email/password trigger
    # no network call as long as no tool is actually invoked.
    monkeypatch.setenv("CAMPUS_EMAIL", "test@example.com")
    monkeypatch.setenv("CAMPUS_PASSWORD", "hunter2")

    async def list_tools() -> list[str]:
        async with Client(mcp) as client:
            result = await client.list_tools()
        return [tool.name for tool in result.tools]

    assert sorted(asyncio.run(list_tools())) == [
        "get_athlete_paces",
        "get_athlete_profile",
        "get_training_calendar",
    ]


def test_smart_training_query_param_names() -> None:
    # Pinned on purpose: /smart-training wants from/to while /logged-sessions
    # wants startDate/endDate. Getting either wrong raises no error -- the API
    # answers 200 and ignores the filter -- so only a test catches the drift.
    client = RecordingClient()
    asyncio.run(_fetch_weeks(client, 0, WEEK_MS - 1))
    path, params = client.calls[0]
    assert path == "/smart-training"
    assert set(params) == {"from", "to"}


def test_logged_sessions_query_param_names() -> None:
    client = RecordingClient()
    asyncio.run(_fetch_logged(client, 0, WEEK_MS - 1))
    assert client.calls == [
        ("/logged-sessions", {"startDate": 0, "endDate": WEEK_MS - 1})
    ]


def test_fetch_weeks_chunks_by_four_weeks() -> None:
    client = RecordingClient()
    asyncio.run(_fetch_weeks(client, 0, 6 * WEEK_MS - 1))
    windows = [(p["from"], p["to"]) for _, p in client.calls]
    assert windows == [(0, MAX_CHUNK_MS - 1), (MAX_CHUNK_MS, 6 * WEEK_MS - 1)]


def test_fetch_logged_drops_sessions_outside_the_window() -> None:
    # Belt and braces: the tool stays correct even if the server-side filter
    # stops being applied.
    client = RecordingClient(
        [
            {"activityDate": 5_000, "title": "inside"},
            {"activityDate": WEEK_MS * 9, "title": "way outside"},
        ]
    )
    sessions = asyncio.run(_fetch_logged(client, 0, WEEK_MS - 1))
    assert [s["title"] for s in sessions] == ["inside"]
