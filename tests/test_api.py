"""Async HTTP contract, index discovery, caching and failure recovery."""

import re
from datetime import UTC, datetime, timedelta

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.shmu.api import ShmuClient, ShmuError
from custom_components.shmu.const import DATA_URL, PRODUCTS_URL, STATIONS_URL

NOW = datetime(2026, 10, 8, 8, tzinfo=UTC)
INDEX = f"{PRODUCTS_URL}?station=32397"
ALADIN = f"{DATA_URL}/aladin/2026-10-08/32397_2026-10-08_00.json"
ECMWF = f"{DATA_URL}/ecmwf/2026-10-07/32397_2026-10-07_12.json"


def products():
    return {
        "station": {"station_id": 32397},
        "data": [
            {
                "type": "aladin",
                "runtime": 1791417600,
                "file_link": ALADIN.removeprefix(DATA_URL + "/"),
            },
            {
                "type": "ecmwf",
                "runtime": 1791374400,
                "file_link": ECMWF.removeprefix(DATA_URL + "/"),
            },
        ],
    }


async def test_station_list(fixture_data):
    async with aiohttp.ClientSession() as session:
        with aioresponses() as mock:
            mock.get(STATIONS_URL, payload=fixture_data("stations"))
            stations = await ShmuClient(session, "32397").stations()
            assert stations["32397"]["name"] == "Veľký Šariš"
            assert stations["32397"]["latitude"] == 49.04


async def test_success_and_cache(fixture_data):
    async with aiohttp.ClientSession() as session:
        client = ShmuClient(session, "32397")
        with aioresponses() as mock:
            mock.get(INDEX, payload=products(), repeat=True)
            mock.get(ALADIN, payload=fixture_data("aladin"))
            mock.get(ECMWF, payload=fixture_data("ecmwf"))
            mock.get(
                f"{DATA_URL}/aladin/2026-10-07/32397_2026-10-07_18.json",
                payload=shift_aladin(fixture_data, -6),
            )
            data = await client.fetch("combined", NOW)
            assert data.degraded_models == []
            # No second JSON response registered: this fails if the cache is bypassed.
            again = await client.fetch("combined", NOW + timedelta(minutes=30))
            assert again.runs == data.runs
            assert len(mock.requests) == 4
            assert all(
                len(calls) == (2 if str(url) == INDEX else 1)
                for (_, url), calls in mock.requests.items()
            )


async def test_latest_06_run_missing_falls_back_to_00(fixture_data):
    index = products()
    latest = f"{DATA_URL}/aladin/2026-10-08/32397_2026-10-08_06.json"
    index["data"].insert(
        0,
        {"type": "aladin", "runtime": 1791439200, "file_link": latest.removeprefix(DATA_URL + "/")},
    )
    async with aiohttp.ClientSession() as session:
        with aioresponses() as mock:
            mock.get(INDEX, payload=index)
            mock.get(latest, status=404)
            mock.get(ALADIN, payload=fixture_data("aladin"))
            data = await ShmuClient(session, "32397").fetch("aladin", NOW)
            assert data.degraded_models == ["aladin"]
            assert data.runs["aladin"].initialized.hour == 0


async def test_partial_model_failure(fixture_data):
    async with aiohttp.ClientSession() as session:
        with aioresponses() as mock:
            mock.get(INDEX, payload=products())
            mock.get(ALADIN, status=503)
            mock.get(ECMWF, payload=fixture_data("ecmwf"))
            data = await ShmuClient(session, "32397").fetch("combined", NOW)
            assert data.degraded_models == ["aladin"]
            assert set(data.runs) == {"ecmwf"}


async def test_index_outage_uses_cache_then_expires(fixture_data):
    async with aiohttp.ClientSession() as session:
        client = ShmuClient(session, "32397")
        with aioresponses() as mock:
            mock.get(INDEX, payload=products())
            mock.get(ALADIN, payload=fixture_data("aladin"))
            await client.fetch("aladin", NOW)
            mock.get(re.compile(r"https://www.shmu.sk/.*"), status=503, repeat=True)
            recovered = await client.fetch("aladin", NOW + timedelta(hours=1))
            assert recovered.degraded_models == ["aladin"]
            with pytest.raises(ShmuError):
                await client.fetch("aladin", NOW + timedelta(hours=49))


@pytest.mark.parametrize(
    "body", [{}, [], {"station": {}}, {"station": {"station_id": 32397}, "data": [None]}]
)
async def test_bad_index_uses_bounded_filename_fallback(fixture_data, body):
    async with aiohttp.ClientSession() as session:
        with aioresponses() as mock:
            mock.get(INDEX, payload=body)
            mock.get(f"{DATA_URL}/aladin/2026-10-08/32397_2026-10-08_06.json", status=404)
            mock.get(ALADIN, payload=fixture_data("aladin"))
            data = await ShmuClient(session, "32397").fetch("aladin", NOW)
            assert data.runs["aladin"]


async def test_wrong_station_payload_is_rejected(fixture_data):
    data = fixture_data("aladin")
    data["si_id"] = "123"
    async with aiohttp.ClientSession() as session:
        with aioresponses() as mock:
            mock.get(INDEX, payload=products())
            mock.get(ALADIN, payload=data)
            with pytest.raises(ShmuError):
                await ShmuClient(session, "32397").fetch("aladin", NOW)


async def test_new_run_keeps_earlier_hours_today(fixture_data):
    from unittest.mock import AsyncMock

    from custom_components.shmu.forecast import ModelRun, parse_run

    client = ShmuClient(None, "32397")
    client._json = AsyncMock(return_value=products())
    first = parse_run(fixture_data("aladin"), "aladin", "32397")
    noon = NOW.replace(hour=12)
    newer = ModelRun(
        "aladin", noon, {t: r for t, r in first.hours.items() if t >= int(noon.timestamp())}
    )
    client._model = AsyncMock(side_effect=[(first, False), (newer, False)])
    before = await client.fetch("aladin", NOW)
    after = await client.fetch("aladin", noon)
    assert min(after.hours) == min(before.hours)
    assert after.runs["aladin"].initialized == noon
    assert all(len(hours) <= 25 for hours in client._history.values())


def shift_aladin(fixture_data, hours, temperature=None):
    """Keep the real wire format while synthesizing model cycles for regression tests."""
    payload = fixture_data("aladin")
    initialized = datetime.fromisoformat(payload["data_date_time"].replace("Z", "+00:00"))
    payload["data_date_time"] = (initialized + timedelta(hours=hours)).isoformat()
    for field in payload.values():
        if isinstance(field, dict):
            for row in field["data"]:
                row[0] += hours * 3600
    if temperature is not None:
        for row in payload["Air_temperature_at_2m"]["data"]:
            row[1] = temperature
    return payload


@pytest.mark.parametrize("mode", ["aladin", "combined"])
async def test_afternoon_restart_recovers_morning_low_without_changing_future(fixture_data, mode):
    from custom_components.shmu.forecast import today_extreme

    now = NOW.replace(hour=20)
    paths = [("2026-10-08", 12, 12, 15), ("2026-10-08", 0, 0, 2), ("2026-10-07", 18, -6, 5)]
    index = products()
    index["data"] = [r for r in index["data"] if r["type"] != "aladin"]
    async with aiohttp.ClientSession() as session:
        with aioresponses() as mock:
            for day, hour, delta, temperature in paths:
                path = f"aladin/{day}/32397_{day}_{hour:02d}.json"
                initialized = datetime.fromisoformat(f"{day}T{hour:02d}:00:00+00:00")
                index["data"].append(
                    {"type": "aladin", "runtime": int(initialized.timestamp()), "file_link": path}
                )
                mock.get(
                    f"{DATA_URL}/{path}", payload=shift_aladin(fixture_data, delta, temperature)
                )
            mock.get(INDEX, payload=index, repeat=True)
            mock.get(f"{DATA_URL}/aladin/2026-10-08/32397_2026-10-08_06.json", status=404)
            mock.get(ECMWF, payload=fixture_data("ecmwf"))
            client = ShmuClient(session, "32397")
            data = await client.fetch(mode, now)
            result = today_extreme(data.hours, "native_temperature", "min", now)
            assert result["value"] == 2
            assert result["coverage_complete"] and result["value_hours"] == 24
            assert data.hours[int(now.timestamp())]["native_temperature"] == 15
            assert (
                data.hours[int((now + timedelta(days=1)).timestamp())]["native_temperature"] == 15
            )
            assert data.runs["aladin"].initialized.hour == 12
            # The oldest valid cycle supplies only the two missing midnight hours.
            midnight = int(now.replace(hour=0).timestamp()) - 2 * 3600
            assert data.hours[midnight]["native_temperature"] == 5
            # Complete history does not trigger more downloads on the next refresh.
            requests_before = sum(len(calls) for calls in mock.requests.values())
            again = await client.fetch(mode, now + timedelta(minutes=30))
            assert today_extreme(again.hours, "native_temperature", "min", now)["value"] == 2
            assert sum(len(calls) for calls in mock.requests.values()) == requests_before + 1


async def test_history_failure_preserves_current_forecast_and_reports_partial_day(fixture_data):
    from custom_components.shmu.forecast import today_extreme

    now = NOW.replace(hour=20)
    latest = f"{DATA_URL}/aladin/2026-10-08/32397_2026-10-08_12.json"
    index = {
        "station": {"station_id": 32397},
        "data": [
            {
                "type": "aladin",
                "runtime": int(now.replace(hour=12).timestamp()),
                "file_link": latest.removeprefix(DATA_URL + "/"),
            }
        ],
    }
    async with aiohttp.ClientSession() as session:
        with aioresponses() as mock:
            mock.get(INDEX, payload=index)
            mock.get(latest, payload=shift_aladin(fixture_data, 12, 15))
            mock.get(re.compile(r"https://www.shmu.sk/data/.*"), status=404, repeat=True)
            data = await ShmuClient(session, "32397").fetch("aladin", now)
            result = today_extreme(data.hours, "native_temperature", "min", now)
            assert result["value"] == 15 and not result["coverage_complete"]
            assert result["value_hours"] == 10
            assert len(mock.requests) == 6  # Index + latest run + at most four older cycles.
