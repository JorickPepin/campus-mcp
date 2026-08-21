"""Pure functions that strip Campus API payloads down to what an LLM needs."""

from datetime import UTC, datetime, timedelta
from typing import Any

WEEK_MS = 604_800_000
DAY_MS = 86_400_000

# How a *planned* session felt relative to what the plan asked for. The scale is
# always relative: Campus labels it against the session's own difficulty (1-6),
# so rating -2 reads "vraiment trop facile" on an easy run and "moyennement
# difficile" on a hard one. Only -2/0/2 are ever seen in the data; -1 and +1
# survive in the API's label table and are mapped so they can't come back as null.
SESSION_RATING_AXIS = {
    -2: "easier_than_expected",
    -1: "slightly_easier_than_expected",  # legacy scale, never observed
    0: "as_expected",
    1: "slightly_harder_than_expected",  # legacy scale, never observed
    2: "harder_than_expected",
}

# Out-of-plan sessions have no plan to be compared against, so the app asks a
# plain difficulty question ("facile / modéré / difficile") and stores the answer
# in the same field. Same numbers, different question -- hence a different axis
# and, downstream, a different output key.
LOGGED_EFFORT_AXIS = {-2: "easy", 0: "moderate", 2: "hard"}

_REAL_METRICS = {
    "averageHeartRateInBeatsPerMinute": "avg_heart_rate",
    "averageRunCadenceInStepsPerMinute": "cadence_spm",
    "totalElevationGainInMeters": "elevation_gain_m",
    "activeCalories": "calories",
}

_LOGGED_METRICS = {
    "averageHeartRate": "avg_heart_rate",
    "maxHeartRate": "max_heart_rate",
    "averageRunCadence": "cadence_spm",
    "totalElevationGainInMeters": "elevation_gain_m",
    "activeCalories": "calories",
}


def iso_to_ms(date_str: str) -> int:
    """Parse an ISO date (YYYY-MM-DD) as midnight UTC, in ms."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        raise ValueError(f"Invalid date {date_str!r}, expected YYYY-MM-DD") from None
    return int(dt.timestamp() * 1000)


def ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%d")


def current_week_bounds(now: datetime | None = None) -> tuple[int, int]:
    """Return (monday, sunday end) of the current week as UTC ms timestamps.

    Campus weekDate values are Mondays at 00:00 UTC.
    """
    now = now or datetime.now(UTC)
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
    paces: list[dict[str, Any]] = week.get("estimatedPaces", [])
    return paces


def _copy_metrics(
    note: dict[str, Any], mapping: dict[str, str], metrics: dict[str, Any]
) -> None:
    """Copy the mapped keys that actually carry a value.

    `maxHeartRate` and friends are frequently present but null; an explicit null
    reads as "measured zero" to a model, so drop it instead.
    """
    for raw_key, out_key in mapping.items():
        if note.get(raw_key) is not None:
            metrics[out_key] = note[raw_key]


def _feedback(
    note: dict[str, Any],
    *,
    comment_key: str,
    rating_key: str,
    rating_axis: dict[int, str],
) -> dict[str, Any]:
    """The athlete's own report, for a planned or an out-of-plan session.

    The condition list is identical on both sides, but everything else differs:
    the comment field is named `sessionComment` vs `notes`, and `sessionRating`
    answers a different question -- hence the caller-supplied axis and key.
    """
    feedback: dict[str, Any] = {}
    if note.get(comment_key):  # "" is the common case: nothing to say
        feedback["comment"] = note[comment_key]
    if "sessionRating" in note:  # 0 is a real answer, don't test truthiness
        rating = rating_axis.get(note["sessionRating"])
        if rating is not None:  # off-scale value: say nothing rather than null
            feedback[rating_key] = rating
    if note.get("sessionConditions"):  # [] means nothing worth flagging
        feedback["conditions"] = note["sessionConditions"]
    return feedback


def slim_session(
    session: dict[str, Any], *, include_zones: bool = False
) -> dict[str, Any]:
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
        if "pace" in note:
            # Same unit as estimatedPaces and zones[].pace, so the LLM can compare the
            # session to its target without a round trip to the source service.
            metrics["real_pace_sec_per_km"] = round(note["pace"])
        _copy_metrics(note, _REAL_METRICS, metrics)
        if "completionDate" in note:
            slim["completed_at"] = datetime.fromtimestamp(
                note["completionDate"] / 1000, tz=UTC
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Join key for the source service's own MCP/API (e.g. Strava activity
        # streams). Manual entries have no external id.
        if note.get("source"):
            slim["activity_source"] = note["source"]
        if note.get("externalId"):
            slim["activity_id"] = note["externalId"]

        feedback = _feedback(
            note,
            comment_key="sessionComment",
            rating_key="rating",
            rating_axis=SESSION_RATING_AXIS,
        )
        if feedback:
            slim["feedback"] = feedback
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


def slim_logged_session(session: dict[str, Any]) -> dict[str, Any]:
    """Slim an out-of-plan session down to the shape of a planned one.

    Same output grammar as `slim_session` on purpose, minus what cannot exist
    here: no `expected_*` (nothing was planned) and no `zones`.
    """
    distance = session.get("distance") or 0
    duration = session.get("duration") or 0
    metrics: dict[str, Any] = {
        "real_distance_km": round(distance, 2),
        "real_duration_min": int(duration / 60),
    }
    if distance > 0:
        # Not served by the API, unlike a racingNote. Same unit as
        # estimatedPaces and zones[].pace so the LLM can compare directly.
        metrics["real_pace_sec_per_km"] = round(duration / distance)
    _copy_metrics(session, _LOGGED_METRICS, metrics)

    slim: dict[str, Any] = {
        "name": session.get("title"),
        "type": session.get("sport"),
        "status": "done",  # An out-of-plan session only exists because it was run.
        "metrics": metrics,
    }
    if "activityDate" in session:
        slim["completed_at"] = datetime.fromtimestamp(
            session["activityDate"] / 1000, tz=UTC
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Same join keys as slim_session, so both kinds of session cross-reference
    # the source service the same way.
    if session.get("source"):
        slim["activity_source"] = session["source"]
    if session.get("externalId"):
        slim["activity_id"] = session["externalId"]

    # Deliberately not "rating": the athlete was asked plain difficulty, with no
    # plan to compare against. A separate key makes the two scales impossible to
    # conflate downstream.
    feedback = _feedback(
        session,
        comment_key="notes",
        rating_key="perceived_effort",
        rating_axis=LOGGED_EFFORT_AXIS,
    )
    if feedback:
        slim["feedback"] = feedback
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


def _with_totals(
    week_stats: dict[str, Any], logged: list[dict[str, Any]]
) -> dict[str, Any]:
    """Add out-of-plan and true totals without touching the plan's own numbers.

    `realDistance` stays what Campus means by it -- how much of the *plan* was
    run -- because that is what plan adherence is read from. The out-of-plan and
    total keys are always emitted, even at 0: a missing total would read as
    "no data" rather than "nothing outside the plan".
    """
    out_distance = sum(s.get("distance") or 0 for s in logged)
    out_duration = sum(s.get("duration") or 0 for s in logged)
    real_distance = week_stats.get("realDistance") or 0
    real_duration = week_stats.get("realDuration") or 0
    return {
        **week_stats,
        "outOfPlanDistance": round(out_distance, 2),
        "outOfPlanDuration": round(out_duration),
        "totalRealDistance": round(real_distance + out_distance, 2),
        "totalRealDuration": round(real_duration + out_duration),
    }


def build_calendar(
    weeks: list[dict[str, Any]],
    logged: list[dict[str, Any]],
    *,
    include_zones: bool = False,
) -> list[dict[str, Any]]:
    """Assemble the calendar, folding out-of-plan sessions into their week.

    Out-of-plan sessions are invisible to /smart-training: they are missing from
    `sessions[]` *and* uncounted in `weekStats`. Folding them in here means no
    caller can total up a week and silently under-report it.
    """
    by_week: dict[Any, list[dict[str, Any]]] = {}
    for session in logged:
        by_week.setdefault(session.get("weekDate"), []).append(session)

    calendar = []
    for week in weeks:
        week_logged = by_week.pop(week.get("weekDate"), [])
        slim = slim_week(week, include_zones=include_zones)
        slim["weekStats"] = _with_totals(slim["weekStats"], week_logged)
        slim["out_of_plan_sessions"] = [slim_logged_session(s) for s in week_logged]
        calendar.append(slim)

    # Sessions run during a week with no plan at all (a break, between two
    # plans) have no week to attach to. Emit a stub rather than drop them --
    # this whole change is about not losing sessions.
    empty_stats = dict.fromkeys(
        ("expectedDistance", "expectedDuration", "realDistance", "realDuration"), 0
    )
    for week_date, week_logged in by_week.items():
        calendar.append(
            {
                "week_start": ms_to_iso(week_date) if week_date is not None else None,
                "weekStats": _with_totals(empty_stats, week_logged),
                "goalDuration": {},
                "sessions": [],
                "out_of_plan_sessions": [slim_logged_session(s) for s in week_logged],
            }
        )

    calendar.sort(key=lambda w: w["week_start"] or "")
    return calendar
