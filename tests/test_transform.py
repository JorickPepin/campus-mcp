import json
from datetime import UTC, datetime

import pytest

from campus_mcp.transform import (
    WEEK_MS,
    current_week_bounds,
    extract_paces,
    extract_profile,
    iso_to_ms,
    ms_to_iso,
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
