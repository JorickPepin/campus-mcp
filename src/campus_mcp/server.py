"""Unofficial MCP server for the Campus Coach training platform."""

import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from importlib.metadata import version as pkg_version
from typing import Any

from mcp.server.mcpserver import Context, MCPServer

from campus_mcp.auth import TokenStore
from campus_mcp.client import CampusClient
from campus_mcp.transform import (
    DAY_MS,
    WEEK_MS,
    build_calendar,
    current_week_bounds,
    extract_paces,
    extract_profile,
    iso_to_ms,
)

MAX_CHUNK_MS = 4 * WEEK_MS


@dataclass
class AppContext:
    client: CampusClient


@asynccontextmanager
async def lifespan(_server: MCPServer) -> AsyncGenerator[AppContext]:
    email = os.environ.get("CAMPUS_EMAIL")
    password = os.environ.get("CAMPUS_PASSWORD")
    if email and password:
        # Credentials mode: don't touch the token file, so a session
        # configured for another account can't clobber the saved tokens.
        client = CampusClient(email=email, password=password)
    else:
        store = TokenStore()
        if store.load() is None:
            raise RuntimeError(
                f"No saved tokens at {store.path} and no CAMPUS_EMAIL/"
                "CAMPUS_PASSWORD set. Run `uvx --from "
                "git+https://github.com/JorickPepin/campus-mcp "
                "campus-mcp-auth` once, or set both environment variables."
            )
        client = CampusClient(token_store=store)
    try:
        yield AppContext(client=client)
    finally:
        await client.close()


mcp = MCPServer("campus", version=pkg_version("campus-mcp"), lifespan=lifespan)


def _client(ctx: Context[AppContext]) -> CampusClient:
    return ctx.request_context.lifespan_context.client


async def _fetch_weeks(
    client: CampusClient, start: int, end: int
) -> list[dict[str, Any]]:
    """Fetch smart-training weeks over [start, end], in chunks of 4 weeks max."""
    weeks: list[dict[str, Any]] = []
    chunk_start = start
    while chunk_start < end:
        chunk_end = min(chunk_start + MAX_CHUNK_MS - 1, end)
        weeks.extend(
            await client.get(
                "/smart-training", params={"from": chunk_start, "to": chunk_end}
            )
        )
        chunk_start = chunk_end + 1
    return weeks


async def _fetch_logged(
    client: CampusClient, start: int, end: int
) -> list[dict[str, Any]]:
    """Fetch out-of-plan sessions over [start, end], in a single call.

    No 4-week chunking: that ceiling belongs to /smart-training, and this
    endpoint happily answers a one-year window.
    """
    sessions: list[dict[str, Any]] = await client.get(
        "/logged-sessions", params={"startDate": start, "endDate": end}
    )
    return [s for s in sessions if start <= (s.get("activityDate") or start) <= end]


@mcp.tool()
async def get_athlete_profile(ctx: Context[AppContext]) -> dict[str, Any]:
    """Get the athlete's physical profile: gender, age, runner type, target
    weekly mileage, experience. Use it to ground any training advice."""
    user_infos = await _client(ctx).get("/account/user-infos")
    return extract_profile(user_infos)


@mcp.tool()
async def get_athlete_paces(ctx: Context[AppContext]) -> list[dict[str, Any]]:
    """Get the athlete's current training pace references (VMA, thresholds,
    fundamental endurance, race paces...). Values are in seconds per km."""
    start, end = current_week_bounds()
    weeks = await _client(ctx).get("/smart-training", params={"from": start, "to": end})
    if not weeks:
        return []
    return extract_paces(weeks[0])


@mcp.tool()
async def get_training_calendar(
    ctx: Context[AppContext],
    from_date: str | None = None,
    to_date: str | None = None,
    include_zones: bool = False,
) -> list[dict[str, Any]]:
    """Get training weeks (planned sessions, planned vs actual stats) between
    two ISO dates (YYYY-MM-DD, UTC). Without dates, returns the entire
    *currently active* training plan; querying past plans requires explicit
    dates. Set include_zones=True only when you need the detailed pace-zone
    structure of sessions (it is verbose); week-level summaries don't need it.

    Each week holds two session lists. `sessions` is the plan. Beside it,
    `out_of_plan_sessions` are runs the athlete logged outside the plan --
    most often a planned session split across several activities, sometimes an
    extra run. They have no `expected_*` metrics because nothing was planned
    for them; that is normal, not missing data.

    Read `weekStats` accordingly, and never total the sessions by hand:

    - `expectedDistance` / `expectedDuration`: what the plan asked for.
    - `realDistance` / `realDuration`: how much of *the plan* was run. Use these
      to judge plan adherence.
    - `outOfPlanDistance` / `outOfPlanDuration`: the rest.
    - `totalRealDistance` / `totalRealDuration`: what the athlete actually ran.
      Use these for training load, weekly volume, or any "how much did I run"
      question. Distances are in km, durations in seconds.

    Done sessions carry a `feedback` object holding the athlete's own report,
    which you should weigh at least as heavily as the raw numbers:

    - `rating`: how the session felt against what the plan expected for that
      session type. "as_expected" is the normal answer, not missing data.
    - `comment`: free text, often explains away an anomaly the metrics alone
      would flag (a treadmill run, a meal right before, a pacing partner).
    - `conditions`: tags the athlete ticked at validation time, picked from
      this closed list — adverse: MinorInjury, Sickness, Tiredness, PMS,
      NoMotivation, PaceTooFast, LackOfTime, TechnicalIssue, Hot, Rain,
      Terrain; favourable: IdealConditions, InShape, PeakMotivation,
      GreatLegs.

    Out-of-plan sessions carry `comment` and `conditions` the same way, but
    their effort field is named `perceived_effort` (easy / moderate / hard) and
    is not the same scale as `rating`. Nothing was planned for them, so the
    athlete was asked plain difficulty, with no target to compare against. Read
    it as absolute perceived effort: `easy` on a short easy run is the expected
    answer and the sign of a well-run session — never treat it as evidence of
    under-training or as a reason to suggest a harder session."""
    client = _client(ctx)

    from_ms = iso_to_ms(from_date) if from_date is not None else None
    to_ms = iso_to_ms(to_date) + DAY_MS - 1 if to_date is not None else None

    if from_ms is None or to_ms is None:
        start, end = current_week_bounds()
        current = await client.get("/smart-training", params={"from": start, "to": end})
        goal = current[0].get("goalDuration") if current else None
        if not goal:
            raise ValueError(
                "No active training plan this week, so the plan bounds cannot "
                "be inferred. Call again with explicit from_date and to_date "
                "(YYYY-MM-DD) covering the period you want."
            )
        week = current[0]
        plan_start = week["weekDate"] - (goal["index"] - 1) * WEEK_MS
        plan_end = plan_start + goal["durationInWeeks"] * WEEK_MS - 1
        from_ms = from_ms if from_ms is not None else plan_start
        to_ms = to_ms if to_ms is not None else plan_end

    weeks, logged = await asyncio.gather(
        _fetch_weeks(client, from_ms, to_ms),
        _fetch_logged(client, from_ms, to_ms),
    )
    return build_calendar(weeks, logged, include_zones=include_zones)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
