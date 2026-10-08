"""Exercise the real HA config flow, weather service and unload lifecycle."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant import config_entries, loader
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry, entity_registry

from custom_components.shmu.api import ForecastData, ShmuError
from custom_components.shmu.forecast import merge_runs, parse_run


@pytest.fixture
async def hass(tmp_path):
    (tmp_path / "custom_components").symlink_to(
        Path.cwd() / "custom_components", target_is_directory=True
    )
    instance = HomeAssistant(str(tmp_path))
    instance.config.time_zone = "Europe/Bratislava"
    instance.config.latitude = 49.04
    instance.config.longitude = 21.2
    instance.config.skip_pip = True
    loader.async_setup(instance)
    instance.config_entries = config_entries.ConfigEntries(instance, {})
    await instance.config_entries.async_initialize()
    if hasattr(device_registry, "async_setup"):
        device_registry.async_setup(instance)
    await device_registry.async_load(instance)
    await entity_registry.async_load(instance)
    # Networking is mocked; avoid initializing multicast discovery in this harness.
    with (
        patch("custom_components.shmu.config_flow.async_get_clientsession", return_value=None),
        patch("custom_components.shmu.coordinator.async_get_clientsession", return_value=None),
    ):
        yield instance
        await instance.async_stop(force=True)


def shifted_data(fixture_data):
    # Preserve all relative source intervals while making the fixture current.
    now = datetime.now(UTC)
    new_init = now.replace(hour=0, minute=0, second=0, microsecond=0)
    runs = {}
    for model in ("aladin", "ecmwf"):
        payload = fixture_data(model)
        old = datetime.fromisoformat(payload["data_date_time"].replace("Z", "+00:00"))
        delta = int((new_init - old).total_seconds())
        payload["data_date_time"] = new_init.isoformat()
        for field in payload.values():
            if isinstance(field, dict):
                for row in field["data"]:
                    row[0] += delta
        runs[model] = parse_run(payload, model, "32397")
    return ForecastData(runs, merge_runs(runs, "combined"), [])


async def test_ui_setup_weather_service_options_and_unload(hass, fixture_data):
    data = shifted_data(fixture_data)
    stations = {
        "32397": {
            "station_id": "32397",
            "name": "Veľký Šariš",
            "latitude": 49.04,
            "longitude": 21.2,
        }
    }
    with (
        patch("custom_components.shmu.api.ShmuClient.stations", AsyncMock(return_value=stations)),
        patch("custom_components.shmu.api.ShmuClient.fetch", AsyncMock(return_value=data)),
    ):
        form = await hass.config_entries.flow.async_init("shmu", context={"source": "user"})
        assert form["type"] == "form"
        created = await hass.config_entries.flow.async_configure(
            form["flow_id"], {"station_id": "32397", "forecast_mode": "combined"}
        )
        assert created["type"] == "create_entry"
        entry = created["result"]
        await hass.async_block_till_done()
        assert entry.state is config_entries.ConfigEntryState.LOADED
        entities = hass.states.async_all("weather")
        assert len(entities) == 1
        entity_id = entities[0].entity_id
        assert entities[0].state not in ("unknown", "unavailable")
        assert entities[0].attributes["current_weather_source"] == "forecast_model"
        assert entities[0].attributes["temperature_unit"] == "°C"
        for kind in ("hourly", "daily"):
            response = await hass.services.async_call(
                "weather",
                "get_forecasts",
                {"entity_id": entity_id, "type": kind},
                blocking=True,
                return_response=True,
            )
            assert len(response[entity_id]["forecast"]) > 1
        # Dashboard forecast subscriptions receive coordinator refreshes too.
        weather = hass.data["weather"].get_entity(entity_id)
        listener = Mock()
        unsubscribe = weather.async_subscribe_forecast("hourly", listener)
        entry.runtime_data.async_set_updated_data(data)
        await hass.async_block_till_done()
        assert listener.called
        unsubscribe()
        entry.runtime_data.async_set_update_error(ShmuError("offline"))
        await hass.async_block_till_done()
        assert hass.states.get(entity_id).state == "unavailable"
        entry.runtime_data.async_set_updated_data(data)
        await hass.async_block_till_done()
        assert hass.states.get(entity_id).state not in ("unknown", "unavailable")
        duplicate = await hass.config_entries.flow.async_init(
            "shmu",
            context={"source": "user"},
            data={"station_id": "32397", "forecast_mode": "combined"},
        )
        assert duplicate["reason"] == "already_configured"
        options = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            options["flow_id"], {"forecast_mode": "ecmwf"}
        )
        assert result["type"] == "create_entry"
        await hass.async_block_till_done()
        assert entry.runtime_data.mode == "ecmwf"
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert hass.states.get(entity_id).state == "unavailable"


async def test_station_failure_can_retry(hass):
    with patch(
        "custom_components.shmu.api.ShmuClient.stations",
        AsyncMock(side_effect=ShmuError("offline")),
    ):
        form = await hass.config_entries.flow.async_init("shmu", context={"source": "user"})
        assert form["errors"] == {"base": "cannot_connect"}
    stations = {
        "32397": {
            "station_id": "32397",
            "name": "Veľký Šariš",
            "latitude": 49.04,
            "longitude": 21.2,
        }
    }
    with patch("custom_components.shmu.api.ShmuClient.stations", AsyncMock(return_value=stations)):
        retry = await hass.config_entries.flow.async_configure(form["flow_id"], {})
        assert retry["type"] == "form"
        assert not retry["errors"]


async def test_forecast_unavailable_does_not_create_entry(hass):
    stations = {
        "32397": {
            "station_id": "32397",
            "name": "Veľký Šariš",
            "latitude": 49.04,
            "longitude": 21.2,
        }
    }
    with (
        patch("custom_components.shmu.api.ShmuClient.stations", AsyncMock(return_value=stations)),
        patch(
            "custom_components.shmu.api.ShmuClient.fetch",
            AsyncMock(side_effect=ShmuError("offline")),
        ),
    ):
        form = await hass.config_entries.flow.async_init(
            "shmu",
            context={"source": "user"},
            data={"station_id": "32397", "forecast_mode": "combined"},
        )
        assert form["type"] == "form"
        assert form["errors"] == {"base": "cannot_connect"}
