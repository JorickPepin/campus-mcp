import json
from datetime import UTC, datetime

import pytest

from campus_mcp.transform import (
    WEEK_MS,
    build_calendar,
    current_week_bounds,
    extract_paces,
    extract_profile,
    iso_to_ms,
    ms_to_iso,
    slim_logged_session,
    slim_session,
    slim_week,
)

BANNED_KEYS = {"description", "coachAdvice", "nutritionTraining", "exercisesBlocks"}


def all_keys(node):
    """Every mapping key in a nested structure.

    Checking keys rather than a substring of the dumped JSON: sessions now carry
    free text written by the athlete, which may well contain a banned word.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from all_keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from all_keys(item)


def test_current_week_bounds_is_monday_utc():
    # Wednesday 2026-06-03 15:30 UTC -> week of Monday 2026-06-01 00:00 UTC
    now = datetime(2026, 6, 3, 15, 30, tzinfo=UTC)
    start, end = current_week_bounds(now)
    assert start == 1780272000000  # matches a real weekDate from the fixture
    assert end == start + WEEK_MS - 1


def test_extract_profile_keeps_only_infos_and_sport_infos():
    user_infos = {
        "infos": {"gender": "male", "age": 30},
        "sportInfos": {"runnerType": "trail"},
        "billing": {"card": "secret"},
        "gdpr": {"consent": True},
        "address": {"street": "x"},
    }
    assert extract_profile(user_infos) == {
        "infos": {"gender": "male", "age": 30},
        "sportInfos": {"runnerType": "trail"},
    }


def test_extract_paces(weeks):
    paces = extract_paces(weeks[0])
    assert {p["slug"] for p in paces} >= {"ef", "seuil60", "vma", "race"}


def test_iso_ms_roundtrip():
    assert iso_to_ms("2026-06-01") == 1780272000000
    assert ms_to_iso(1780272000000) == "2026-06-01"
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        iso_to_ms("01/06/2026")


def test_slim_session_mapping(weeks):
    session = weeks[0]["sessions"][0]  # EF_20, done
    slim = slim_session(session, include_zones=True)
    assert slim["name"] == "EF_20"
    assert slim["type"] == "EF"
    assert slim["status"] == "done"
    assert slim["metrics"]["expected_duration_min"] == 20
    assert slim["metrics"]["real_distance_km"] == 2.97
    assert slim["metrics"]["real_duration_min"] == 20
    assert slim["metrics"]["real_pace_sec_per_km"] == 405
    assert slim["metrics"]["avg_heart_rate"] == 131
    assert slim["metrics"]["cadence_spm"] == 157
    assert slim["metrics"]["elevation_gain_m"] == 0
    assert slim["metrics"]["calories"] == 200
    assert slim["completed_at"] == "2026-06-03T08:08:57Z"
    assert slim["activity_source"] == "strava"
    assert slim["activity_id"] == "0000000000"
    assert slim["feedback"] == {
        "comment": "sur tapis, description du ressenti: FC un peu haute",
        "rating": "harder_than_expected",
        "conditions": ["Hot", "Tiredness"],
    }
    assert slim["zones"] == [{"kind": "Z2", "duration": 1200, "pace": 328}]


def test_slim_session_keeps_neutral_rating(weeks):
    # The majority case: session validated with no comment and no notable
    # conditions. sessionRating 0 means "as expected", not "unanswered" -- a
    # truthiness check here would silently drop the most frequent value.
    slim = slim_session(weeks[0]["sessions"][2])  # EF_35, done
    assert slim["feedback"] == {"rating": "as_expected"}


def test_slim_session_drops_racing_note_noise(weeks):
    slim = slim_session(weeks[0]["sessions"][2])
    dumped = json.dumps(slim)
    for noise in ("deviceName", "Fake Watch", "Course à pied le matin", "_type"):
        assert noise not in dumped


def test_slim_session_omits_zones_by_default(weeks):
    assert "zones" not in slim_session(weeks[0]["sessions"][1])


def test_slim_session_drops_real_metrics_when_not_done(weeks):
    session = dict(weeks[0]["sessions"][0], status="planned")
    slim = slim_session(session)
    assert "real_distance_km" not in slim["metrics"]
    assert "real_duration_min" not in slim["metrics"]
    assert "completed_at" not in slim
    assert "activity_source" not in slim
    assert "activity_id" not in slim
    assert "avg_heart_rate" not in slim["metrics"]
    assert "feedback" not in slim


def test_slim_week_bans_noise(weeks):
    slim = slim_week(weeks[0], include_zones=True)
    assert slim["week_start"] == "2026-06-01"
    assert slim["weekStats"]["realDistance"] > 0
    assert slim["goalDuration"] == {"durationInWeeks": 18, "index": 12}
    assert BANNED_KEYS.isdisjoint(all_keys(slim))
    # ...and the athlete's own text survives even though it says "description".
    assert "description" in slim["sessions"][0]["feedback"]["comment"]


def test_slim_week_shrinks_payload(weeks):
    raw = json.dumps(weeks[0])
    slim = json.dumps(slim_week(weeks[0]))
    assert len(slim) < len(raw)


def test_slim_logged_session_mapping(logged):
    slim = slim_logged_session(logged[2])  # garmin trail
    assert slim["name"] == "Sortie trail"
    assert slim["type"] == "trail"
    assert slim["status"] == "done"  # a logged session only exists once run
    assert slim["metrics"] == {
        "real_distance_km": 6.5,
        "real_duration_min": 40,
        "real_pace_sec_per_km": 369,  # computed: the API serves no pace here
        "avg_heart_rate": 148,
        "max_heart_rate": 171,
        "cadence_spm": 161,
        "elevation_gain_m": 210,
        "calories": 520,
    }
    assert slim["completed_at"] == "2026-06-06T09:15:00Z"
    assert slim["activity_source"] == "garmin"
    assert slim["activity_id"] == "2222222222"
    assert slim["feedback"] == {
        "perceived_effort": "hard",
        "conditions": ["Terrain", "Hot"],
    }
    # Nothing was planned, so there is nothing to expect -- and no pace zones.
    assert "expected_distance_km" not in slim["metrics"]
    assert "zones" not in slim


def test_slim_logged_session_drops_null_metrics(logged):
    # maxHeartRate is routinely present but null; an explicit null reads as a
    # measured zero to a model.
    slim = slim_logged_session(logged[0])
    assert "max_heart_rate" not in slim["metrics"]
    assert slim["metrics"]["avg_heart_rate"] == 154


def test_slim_logged_session_survives_zero_distance(logged):
    slim = slim_logged_session(logged[1])  # ppg, distance 0
    assert slim["metrics"]["real_distance_km"] == 0
    assert slim["metrics"]["real_duration_min"] == 30
    assert "real_pace_sec_per_km" not in slim  # no division by zero
    # Manual entries have no external id, but keep the source.
    assert slim["activity_source"] == "manual"
    assert "activity_id" not in slim
    assert slim["feedback"] == {
        "comment": "gainage + PPG, description du ressenti: jambes lourdes",
        "perceived_effort": "moderate",  # 0 is an answer, not a missing value
        "conditions": ["Tiredness"],
    }


def test_slim_logged_session_drops_noise(logged):
    dumped = json.dumps(slim_logged_session(logged[2]))
    for noise in ("deviceName", "Fake Watch", "userId", "goalId", "createdAt"):
        assert noise not in dumped


def test_rating_scales_are_not_interchangeable(weeks, logged):
    # Same raw sessionRating, two different questions. On a planned session -2
    # means "easier than the plan asked for"; on an imported easy run it just
    # means the athlete ticked "facile", which is the expected answer. Reporting
    # both as easier_than_expected made a well-run footing look like a session
    # that should have been harder.
    planned = dict(weeks[0]["sessions"][0])
    planned["racingNote"] = dict(planned["racingNote"], sessionRating=-2)
    assert slim_session(planned)["feedback"]["rating"] == "easier_than_expected"

    out_of_plan = slim_logged_session(logged[0])  # sessionRating -2 as well
    assert out_of_plan["feedback"] == {"perceived_effort": "easy"}
    assert "rating" not in out_of_plan["feedback"]


def test_slim_session_maps_the_legacy_rating_steps(weeks):
    # -1 and +1 exist in the API's own label table but never show up in the
    # data. Unmapped, they used to land as a literal "rating": null.
    session = dict(weeks[0]["sessions"][0])
    session["racingNote"] = dict(session["racingNote"], sessionRating=-1)
    slim = slim_session(session)
    assert slim["feedback"]["rating"] == "slightly_easier_than_expected"


@pytest.mark.parametrize("rating", [7, -7, None])
def test_off_scale_rating_is_omitted_not_nulled(weeks, logged, rating):
    session = dict(weeks[0]["sessions"][0])
    session["racingNote"] = dict(session["racingNote"], sessionRating=rating)
    assert "rating" not in slim_session(session)["feedback"]

    assert "perceived_effort" not in slim_logged_session(
        dict(logged[0], sessionRating=rating)
    ).get("feedback", {})


def test_build_calendar_folds_out_of_plan_into_its_week(weeks, logged):
    calendar = build_calendar(weeks, logged)
    week = calendar[0]
    assert week["week_start"] == "2026-06-01"
    # Three of the four logged sessions belong to this week.
    assert [s["name"] for s in week["out_of_plan_sessions"]] == [
        "Course à pied en soirée",
        "Renfo maison",
        "Sortie trail",
    ]
    stats = week["weekStats"]
    assert stats["realDistance"] == 46.95  # untouched: plan adherence
    assert stats["outOfPlanDistance"] == 10.75
    assert stats["totalRealDistance"] == 57.7
    assert stats["outOfPlanDuration"] == 5780
    assert stats["totalRealDuration"] == 18593 + 5780


def test_build_calendar_stubs_a_week_with_no_plan(weeks, logged):
    # A session run during a break has no plan week to attach to. Dropping it
    # would reintroduce exactly the bug this whole thing fixes.
    calendar = build_calendar(weeks, logged)
    assert [w["week_start"] for w in calendar] == ["2026-06-01", "2026-06-08"]
    stub = calendar[1]
    assert stub["sessions"] == []
    assert stub["goalDuration"] == {}
    assert stub["weekStats"]["realDistance"] == 0
    assert stub["weekStats"]["totalRealDistance"] == 2.5
    assert [s["name"] for s in stub["out_of_plan_sessions"]] == ["Footing de récup"]


def test_build_calendar_without_out_of_plan_sessions(weeks):
    # Nominal case: the totals must still be there, at 0. A missing total would
    # read as "no data" instead of "nothing outside the plan".
    week = build_calendar(weeks, [])[0]
    assert week["out_of_plan_sessions"] == []
    stats = week["weekStats"]
    assert stats["outOfPlanDistance"] == 0
    assert stats["outOfPlanDuration"] == 0
    assert stats["totalRealDistance"] == stats["realDistance"]
    assert stats["totalRealDuration"] == stats["realDuration"]


def test_build_calendar_bans_noise(weeks, logged):
    calendar = build_calendar(weeks, logged, include_zones=True)
    assert BANNED_KEYS.isdisjoint(all_keys(calendar))
