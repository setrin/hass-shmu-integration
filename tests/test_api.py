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
            data = await client.fetch("combined", NOW)
            assert data.degraded_models == []
            # No second JSON response registered: this fails if the cache is bypassed.
            again = await client.fetch("combined", NOW + timedelta(minutes=30))
            assert again.runs == data.runs
            assert len(mock.requests) == 3


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
