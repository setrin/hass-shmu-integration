"""Real feed excerpts, strict freshness and independent source failures."""

import json
import ssl
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from custom_components.shmu.api import ShmuError
from custom_components.shmu.live import (
    CET,
    LiveClient,
    district_for_point,
    parse_observation,
    parse_warnings,
)
from custom_components.shmu.stations import get_station
from custom_components.shmu.tls import observation_ssl_context

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 8, 20, tzinfo=UTC)
BA = {"code": "BA", "name": "Bratislava"}
PO = {"code": "PO", "name": "Prešov"}


def warning_source():
    return (FIXTURES / "warnings_ba.html").read_text()


def test_current_website_warning_and_expiry():
    result = parse_warnings(warning_source(), BA, NOW)
    assert len(result["alerts"]) == 1
    alert = result["alerts"][0]
    assert alert["event"] == "Vietor"
    assert alert["level"] == 1
    assert alert["starts_at"] == "2026-10-08T21:00:00+00:00"
    assert alert["ends_at"] == "2026-10-09T02:00:00+00:00"
    assert "potenciálne nebezpečenstvo" in alert["description"]
    assert "<" not in alert["description"]
    assert not parse_warnings(warning_source(), BA, NOW + timedelta(days=1))["alerts"]
    assert not parse_warnings((FIXTURES / "warnings_po.html").read_text(), PO, NOW)["alerts"]


@pytest.mark.parametrize(
    "source",
    [
        "",
        "<html>maintenance</html>",
        "<caption>Meteorologické výstrahy pre okres Bratislava</caption><tbody>New format</tbody>",
    ],
)
def test_warning_failure_never_means_clear(source):
    with pytest.raises(ShmuError):
        parse_warnings(source, BA, NOW)


def test_warning_district_mismatch_and_changed_details():
    with pytest.raises(ShmuError):
        parse_warnings(warning_source(), PO, NOW)
    with pytest.raises(ShmuError):
        parse_warnings(warning_source().replace("Trvanie javu:", "Validity:"), BA, NOW)


def test_multiple_warnings_with_nested_advice_tables():
    source = warning_source()
    second = source[source.index("<tr>") :].replace("Vietor", "Dážď").replace("warn_1", "warn_2")
    second = second.replace("1. stupeň", "2. stupeň")
    alerts = parse_warnings(source + second, BA, NOW)["alerts"]
    assert [(a["event"], a["level"]) for a in alerts] == [("Vietor", 1), ("Dážď", 2)]


def test_city_uses_warning_district_not_measurement_station(fixture_data):
    assert district_for_point(fixture_data("warning_district"), 49.04, 21.2) == PO
    with pytest.raises(ShmuError):
        district_for_point(fixture_data("warning_district"), 0, 0)


def observation_payload():
    return {
        "data": [
            {
                "ind_kli": 11968,
                "minuta": "2026-10-08T21:00:00",
                "t": 12,
                "tlak": 990,
                "vlh_rel": 75,
                "vie_pr_rych": 2,
                "vie_max_rych": 4,
                "vie_pr_smer": 350,
                "dohl": 15000,
            }
        ]
    }


def test_observation_fixed_cet_and_units():
    result = parse_observation(observation_payload(), get_station(11968), NOW)
    assert result["measured_at"] == NOW.isoformat()  # CET, not summer UTC+2.
    assert result["humidity"] == 75
    assert result["native_visibility"] == 15
    assert result["native_wind_speed"] == 2
    assert 1010 < result["native_pressure"] < 1030


def test_real_observation_excerpt(fixture_data):
    payload = fixture_data("observations")
    latest = max(datetime.fromisoformat(r["minuta"]).replace(tzinfo=CET) for r in payload["data"])
    reading = parse_observation(payload, get_station(11968), latest.astimezone(UTC))
    assert reading["measured_at"] == latest.astimezone(UTC).isoformat()
    assert isinstance(reading["native_temperature"], float)


@pytest.mark.parametrize("offset", [31, -3])
def test_observation_stale_and_future_rejected(offset):
    with pytest.raises(ShmuError):
        parse_observation(
            observation_payload(), get_station(11968), NOW + timedelta(minutes=offset)
        )


def test_observation_nulls_bad_values_and_wrong_station():
    payload = observation_payload()
    payload["data"][0].update(tlak=None, vlh_rel=999, vie_pr_rych=float("nan"))
    result = parse_observation(payload, get_station(11968), NOW)
    assert "humidity" not in result and "native_pressure" not in result
    assert "native_wind_speed" not in result
    with pytest.raises(ShmuError):
        parse_observation(payload, get_station(11976), NOW)


async def test_sources_fail_independently_and_recover():
    client = LiveClient(None, 49.04, 21.2)
    client.observations = AsyncMock(side_effect=ShmuError("offline"))
    client.warnings = AsyncMock(return_value={"alerts": []})
    assert await client.fetch(NOW) == {"observation": None, "warnings": {"alerts": []}}
    client.observations = AsyncMock(return_value={"native_temperature": 12})
    client.warnings = AsyncMock(side_effect=ShmuError("offline"))
    assert await client.fetch(NOW) == {"observation": {"native_temperature": 12}, "warnings": None}


async def test_observation_discovery_and_empty_snapshot_fallback():
    client = LiveClient(None, 49.04, 21.2, "11968")
    client._text = AsyncMock(
        side_effect=[
            '<a href="20261008/">day</a><a href="https://evil.invalid/">bad</a>',
            '<a href="aws1min%20-%202026-10-08%2022-00-00.json">latest</a>'
            '<a href="aws1min%20-%202026-10-08%2021-55-00.json">previous</a>',
            '{"data":[]}',
            json.dumps(observation_payload()),
        ]
    )
    result = await client.observations(NOW)
    assert result["station"] == "Košice"
    assert client._text.call_count == 4
    assert all(
        call.args[0].startswith("https://opendata.shmu.sk/") for call in client._text.call_args_list
    )


async def test_model_only_disables_observation_requests():
    client = LiveClient(None, 49.04, 21.2, "model")
    client._text = AsyncMock()
    assert await client.observations(NOW) is None
    client._text.assert_not_called()


def test_tls_keeps_root_and_hostname_verification():
    context = observation_ssl_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
    assert not context.verify_flags & ssl.VERIFY_X509_PARTIAL_CHAIN
