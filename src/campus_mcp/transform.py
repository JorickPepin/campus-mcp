"""Pure functions that strip Campus API payloads down to what an LLM needs."""

from datetime import datetime, timedelta, timezone
from typing import Any

WEEK_MS = 604_800_000
DAY_MS = 86_400_000


def iso_to_ms(date_str: str) -> int:
    """Parse an ISO date (YYYY-MM-DD) as midnight UTC, in ms."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise ValueError(f"Invalid date {date_str!r}, expected YYYY-MM-DD") from None
    return int(dt.timestamp() * 1000)


def ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def current_week_bounds(now: datetime | None = None) -> tuple[int, int]:
    """Return (monday, sunday end) of the current week as UTC ms timestamps.

    Campus weekDate values are Mondays at 00:00 UTC.
    """
    now = now or datetime.now(timezone.utc)
    monday = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start = int(monday.timestamp() * 1000)
    return start, start + WEEK_MS - 1


def extract_profile(user_infos: dict[str, Any]) -> dict[str, Any]:
    """Keep only infos (gender, age...) and sportInfos; drop billing/GDPR/etc."""
    return {
        "infos": user_infos.get("infos", {}),
        "sportInfos": user_infos.get("sportInfos", {}),
    }


def extract_paces(week: dict[str, Any]) -> list[dict[str, Any]]:
    return week.get("estimatedPaces", [])


def slim_session(session: dict[str, Any], *, include_zones: bool = False) -> dict[str, Any]:
    stats = session.get("stats", {})
    metrics: dict[str, Any] = {
        "expected_distance_km": round(stats.get("expectedDistance", 0), 2),
        "expected_duration_min": int(stats.get("expectedDuration", 0) / 60),
    }
    slim: dict[str, Any] = {
        "name": session.get("name"),
        "type": session.get("trainingType"),
        "status": session.get("status"),
        "metrics": metrics,
    }

    if session.get("status") == "done":
        note = session.get("racingNote") or {}
        if "distance" in note:
            metrics["real_distance_km"] = round(note["distance"], 2)
        if "time" in note:
            metrics["real_duration_min"] = int(note["time"] / 60)
        if "completionDate" in note:
            slim["completed_at"] = datetime.fromtimestamp(
                note["completionDate"] / 1000, tz=timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Join key for the source service's own MCP/API (e.g. Strava activity
        # streams). Manual entries have no external id.
        if note.get("source"):
            slim["activity_source"] = note["source"]
        if note.get("externalId"):
            slim["activity_id"] = note["externalId"]
    if include_zones:
        slim["zones"] = [
            {
                "kind": zone.get("kind"),
                "duration": zone.get("duration"),
                "pace": zone.get("pace", {}).get("value"),
            }
            for zone in session.get("paceZones", [])
        ]
    return slim


def slim_week(week: dict[str, Any], *, include_zones: bool = False) -> dict[str, Any]:
    week_date = week.get("weekDate")
    return {
        "week_start": ms_to_iso(week_date) if week_date is not None else None,
        "weekStats": week.get("weekStats", {}),
        "goalDuration": week.get("goalDuration", {}),
        "sessions": [
            slim_session(s, include_zones=include_zones)
            for s in week.get("sessions", [])
        ],
    }
