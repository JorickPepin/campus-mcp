import asyncio

import pytest
from mcp.client import Client

from campus_mcp.server import mcp


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
