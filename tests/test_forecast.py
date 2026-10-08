"""Source semantics, blending, rainfall conservation and calendar boundaries."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.shmu.forecast import (
    ModelRun,
    condition,
    daily_forecasts,
    day_coverage,
    interpolate,
    merge_runs,
    parse_run,
    series,
)


def test_real_aladin(fixture_data):
    run = parse_run(fixture_data("aladin"), "aladin", "32397")
    assert len(run.hours) == 102
    first = run.hours[min(run.hours)]
    assert first["native_temperature"] == 8.009
    assert first["native_pressure"] == 1015.602
    assert first["wind_bearing"] == 111.91
    assert first["native_precipitation"] == 0


def test_real_ecmwf_median_direction_and_cadence(fixture_data):
    data = fixture_data("ecmwf")
    run = parse_run(data, "ecmwf", "32397")
    assert len(run.hours) == 240
    t = min(run.hours)
    assert run.hours[t]["native_temperature"] == 21.547
    assert run.hours[t]["wind_bearing"] == 180
    assert run.hours[t + 3600]["native_temperature"] == pytest.approx(
        21.547 + (18.438 - 21.547) / 3, abs=0.0001
    )
    # Every six-hour median total is represented exactly once across six hours.
    for end, *values in data["Total_precipitation"]["data"]:
        assert sum(
            run.hours[h]["native_precipitation"] for h in range(end - 21600, end, 3600)
        ) == pytest.approx(values[2], abs=0.0004)


def test_combine_prefers_aladin_without_overlap(fixture_data):
    a = parse_run(fixture_data("aladin"), "aladin", "32397")
    e = parse_run(fixture_data("ecmwf"), "ecmwf", "32397")
    merged = merge_runs({"aladin": a, "ecmwf": e}, "combined")
    assert merged[min(a.hours)]["model"] == "aladin"
    assert merged[max(a.hours) + 3600]["model"] == "ecmwf"
    assert list(merged) == sorted(set(a.hours) | set(e.hours))
    assert merge_runs({"aladin": a, "ecmwf": e}, "aladin") == a.hours
    assert merge_runs({"aladin": a, "ecmwf": e}, "ecmwf") == e.hours
    assert merge_runs({"ecmwf": e}, "combined") == e.hours


def test_interval_transition_does_not_count_ecmwf_rain_twice(fixture_data):
    data = fixture_data("ecmwf")
    for row in data["Total_precipitation"]["data"]:
        row[3] = 6
    e = parse_run(data, "ecmwf", "32397")
    end = min(e.hours) + 2 * 3600
    a = ModelRun(
        "aladin",
        e.initialized,
        {t: {**e.hours[t], "native_precipitation": 2} for t in range(min(e.hours), end, 3600)},
    )
    merged = merge_runs({"aladin": a, "ecmwf": e}, "combined")
    assert (
        sum(
            merged[t]["native_precipitation"]
            for t in range(min(e.hours), min(e.hours) + 21600, 3600)
        )
        == 8
    )


def test_missing_values_not_zero_and_wrong_units_rejected(fixture_data):
    data = fixture_data("aladin")
    del data["Mean_sea_level_pressure"]
    data["Air_temperature_at_2m"]["data"][1][1] = None
    data["Total_precipitation"]["data"][1][1] = None
    run = parse_run(data, "aladin", "32397")
    first = min(run.hours)
    assert first + 3600 not in run.hours
    assert "native_precipitation" not in run.hours[first]
    assert "native_pressure" not in run.hours[first]
    data["Air_temperature_at_2m"]["unit"] = "K"
    with pytest.raises(ValueError):
        parse_run(data, "aladin", "32397")


@pytest.mark.parametrize("change", ["station", "model", "time", "columns"])
def test_identity_and_schema_validation(fixture_data, change):
    data = fixture_data("ecmwf")
    if change == "station":
        data["si_id"] = "123"
    if change == "model":
        data["model_name"] = "ALADIN"
    if change == "time":
        data["data_date_time"] = "2026-10-08T00:00"
    if change == "columns":
        data["Air_temperature_at_2m"]["columns"] = ["Time", "x"]
    with pytest.raises(ValueError):
        parse_run(data, "ecmwf", "32397")


def test_series_joins_by_timestamp_and_circular_wind(fixture_data):
    data = fixture_data("aladin")
    data["Wind_speed_at_10m"]["data"].reverse()
    run = parse_run(data, "aladin", "32397")
    assert run.hours[min(run.hours)]["native_wind_speed"] == 1.304
    assert interpolate({0: 350, 7200: 10}, 3600, circular=True) == 0
    assert interpolate({0: 10, 7200: None}, 3600) is None
    assert interpolate({0: 10, 7200: 12}, 10800) is None
    assert interpolate({0: 10, 25200: 12}, 3600) is None
    assert series({"x": {"unit": "mm", "data": [[0, float("nan")]]}}, "x", "mm") == {0: None}


@pytest.mark.parametrize(
    ("start", "expected"), [("2026-03-28T23:00:00+00:00", 23), ("2026-10-24T22:00:00+00:00", 25)]
)
def test_slovak_dst_days(start, expected):
    now = datetime.fromisoformat(start)
    hours = {
        int((now + timedelta(hours=i)).timestamp()): {
            "native_temperature": float(i),
            "native_precipitation": 1,
            "cloud_coverage": 50,
        }
        for i in range(expected)
    }
    daily = daily_forecasts(hours, now)
    assert len(daily) == 1
    assert daily[0]["native_precipitation"] == expected
    assert daily[0]["native_temperature"] == expected - 1
    assert daily[0]["native_templow"] == 0
    assert list(day_coverage(hours, now).values()) == [
        {"hours": expected, "expected_hours": expected}
    ]


def test_partial_days_and_unknown_rain():
    now = datetime(2026, 10, 8, 12, tzinfo=UTC)
    hours = {int(now.timestamp()): {"native_temperature": 12, "cloud_coverage": 90}}
    daily = daily_forecasts(hours, now)
    assert "native_precipitation" not in daily[0]
    assert daily[0]["condition"] == "cloudy"
    assert day_coverage(hours, now)["2026-10-08"]["hours"] == 1


def test_condition_is_conservative():
    assert condition({}, False) is None
    assert condition({"cloud_coverage": 0}, False) == "clear-night"
    assert condition({"cloud_coverage": 0}, True) == "sunny"
    assert condition({"native_precipitation": 1, "snowfall": 1}) == "snowy"
    assert condition({"native_precipitation": 2, "snowfall": 1}) == "snowy-rainy"


def test_daily_rain_is_not_diluted_by_dry_hours():
    now = datetime(2026, 10, 8, tzinfo=UTC)
    hours = {
        int((now + timedelta(hours=i)).timestamp()): {
            "native_temperature": 12,
            "cloud_coverage": 0,
            "native_precipitation": 1 if i == 5 else 0,
        }
        for i in range(22)
    }
    daily = daily_forecasts(hours, now)
    assert daily[0]["condition"] == "rainy"
    assert daily[0]["native_precipitation"] == 1


@pytest.mark.parametrize(
    "start,count", [("2026-03-28T23:00:00+00:00", 23), ("2026-10-24T22:00:00+00:00", 25)]
)
def test_future_day_requires_complete_dst_coverage(start, count):
    day = datetime.fromisoformat(start)
    hours = {
        int((day + timedelta(hours=i)).timestamp()): {"native_temperature": 12}
        for i in range(count)
    }
    assert len(daily_forecasts(hours, day - timedelta(days=1))) == 1
    hours.pop(max(hours))
    assert daily_forecasts(hours, day - timedelta(days=1)) == []
