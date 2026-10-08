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
        with patch(
            "custom_components.shmu.live.LiveClient.fetch",
            AsyncMock(return_value={"observation": None, "warnings": None}),
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
            options["flow_id"], {"forecast_mode": "ecmwf", "observation_station": "model"}
        )
        assert result["type"] == "create_entry"
        await hass.async_block_till_done()
        assert entry.runtime_data.mode == "ecmwf"
        assert entry.runtime_data.live.client.model_only
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


async def test_live_weather_warnings_diagnostics_and_recovery(hass, fixture_data):
    from datetime import timedelta

    from custom_components.shmu.diagnostics import async_get_config_entry_diagnostics

    now = datetime.now(UTC)
    forecast = shifted_data(fixture_data)
    station = {"station_id": "32397", "name": "Veľký Šariš", "latitude": 49.04, "longitude": 21.2}
    observation = {
        "native_temperature": 13.2,
        "humidity": 81,
        "native_wind_speed": 0,
        "native_wind_gust_speed": 4,
        "station": "Košice",
        "distance_km": 42,
        "measured_at": now.isoformat(),
    }
    alert = {
        "level": 2,
        "event": "Vietor",
        "starts_at": (now + timedelta(hours=1)).isoformat(),
        "ends_at": (now + timedelta(hours=2)).isoformat(),
        "description": "Test warning",
    }
    warnings = {
        "district": "Prešov",
        "url": "https://www.shmu.sk/",
        "checked_at": now.isoformat(),
        "alerts": [alert],
    }
    with (
        patch(
            "custom_components.shmu.api.ShmuClient.stations",
            AsyncMock(return_value={"32397": station}),
        ),
        patch("custom_components.shmu.api.ShmuClient.fetch", AsyncMock(return_value=forecast)),
        patch(
            "custom_components.shmu.live.LiveClient.fetch",
            AsyncMock(return_value={"observation": observation, "warnings": warnings}),
        ),
    ):
        created = await hass.config_entries.flow.async_init(
            "shmu",
            context={"source": "user"},
            data={"station_id": "32397", "forecast_mode": "combined"},
        )
        await hass.async_block_till_done()
        entry = created["result"]
        weather = hass.states.async_all("weather")[0].entity_id
        binary = hass.states.async_all("binary_sensor")[0].entity_id
        registry = entity_registry.async_get(hass)
        level = registry.async_get_entity_id("sensor", "shmu", "32397_warning_level")

        def sensor(key):
            return hass.states.get(registry.async_get_entity_id("sensor", "shmu", f"32397_{key}"))

        assert len(hass.states.async_all("sensor")) == 10
        assert sensor("current_temperature").state == "13.2"
        assert sensor("current_temperature").attributes["unit_of_measurement"] == "°C"
        assert sensor("current_temperature").attributes["source"] == "observation"
        assert sensor("current_wind").state == "0.0"
        assert sensor("current_gust").state == "14.4"  # HA metric preference converts m/s to km/h.
        assert sensor("current_wind").attributes["source"] == "observation"
        assert sensor("current_wind").attributes["unit_of_measurement"] == "km/h"
        for key in (
            "today_temperature_min",
            "today_temperature_max",
            "today_wind_min",
            "today_wind_max",
            "today_gust_min",
            "today_gust_max",
        ):
            assert sensor(key).state not in ("unknown", "unavailable")
            assert sensor(key).attributes["source"] == "forecast_model"
            assert "coverage_complete" in sensor(key).attributes
        assert sensor("today_temperature_min").attributes["unit_of_measurement"] == "°C"
        assert "Next 24h" in sensor("today_temperature_min").attributes["friendly_name"]
        assert sensor("today_temperature_min").attributes["expected_hours"] == 24
        assert "forecast_date" not in sensor("today_temperature_min").attributes
        assert float(sensor("today_temperature_min").state) <= float(
            sensor("today_temperature_max").state
        )
        assert hass.states.get(weather).attributes["temperature"] == 13.2
        assert hass.states.get(weather).attributes["humidity"] == 81
        assert hass.states.get(weather).attributes["condition_source"] == "forecast_model"
        assert hass.states.get(binary).state == "on"
        assert hass.states.get(level).state == "0"  # Upcoming only, not yet active.
        assert hass.states.get(level).attributes["highest_upcoming_level"] == 2
        missing_gust = {
            key: value for key, value in observation.items() if key != "native_wind_gust_speed"
        }
        entry.runtime_data.live.async_set_updated_data(
            {"observation": missing_gust, "warnings": warnings}
        )
        await hass.async_block_till_done()
        assert sensor("current_gust").state == "unknown"
        assert sensor("current_gust").attributes["source"] == "observation"

        warnings = {
            **warnings,
            "alerts": [{**alert, "starts_at": (now - timedelta(hours=1)).isoformat()}],
        }
        entry.runtime_data.live.async_set_updated_data(
            {"observation": observation, "warnings": warnings}
        )
        await hass.async_block_till_done()
        assert hass.states.get(level).state == "2"
        diagnostics = str(await async_get_config_entry_diagnostics(hass, entry))
        for private in ("32397", "Prešov", "Košice", "49.04", "21.2", "description"):
            assert private not in diagnostics
        # Forecast outage does not suppress fresh measurements; unavailable sky is honest.
        entry.runtime_data.async_set_update_error(ShmuError("forecast offline"))
        await hass.async_block_till_done()
        assert hass.states.get(weather).attributes["temperature"] == 13.2
        assert hass.states.get(weather).state != "unavailable"
        assert sensor("current_wind").state == "0.0"
        assert sensor("today_temperature_min").state == "unavailable"
        assert sensor("current_temperature").state == "13.2"
        entry.runtime_data.async_set_updated_data(forecast)
        # A warning-source failure must never produce an all-clear.
        entry.runtime_data.live.async_set_updated_data({"observation": None, "warnings": None})
        await hass.async_block_till_done()
        assert sensor("current_wind").attributes["source"] == "forecast_model"
        assert sensor("current_temperature").attributes["source"] == "forecast_model"
        assert float(sensor("current_temperature").state) == pytest.approx(
            hass.states.get(weather).attributes["temperature"], abs=0.1
        )
        assert sensor("current_gust").state not in ("unknown", "unavailable")
        assert hass.states.get(binary).state == "unavailable"
        assert hass.states.get(level).state == "unavailable"
        assert hass.states.get(weather).attributes["current_weather_source"] == "forecast_model"
        # Expired observations are rejected even if no successful refresh replaced them.
        old = {**observation, "measured_at": (now - timedelta(hours=1)).isoformat()}
        entry.runtime_data.live.async_set_updated_data(
            {"observation": old, "warnings": {**warnings, "alerts": []}}
        )
        await hass.async_block_till_done()
        assert hass.states.get(weather).attributes["current_weather_source"] == "forecast_model"
        assert hass.states.get(binary).state == "off"
        assert hass.states.get(level).state == "0"
        from custom_components.shmu.forecast import LOCAL_TZ

        # The registered clock callback advances the rolling window without a source refresh.
        tomorrow = (now.astimezone(LOCAL_TZ) + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        daily_id = registry.async_get_entity_id("sensor", "shmu", "32397_today_temperature_min")
        daily_entity = hass.data["sensor"].get_entity(daily_id)
        with patch("custom_components.shmu.sensor.datetime") as clock:
            clock.now.return_value = tomorrow.astimezone(UTC)
            daily_entity._clock_update(tomorrow.astimezone(UTC))
            assert (
                sensor("today_temperature_min").attributes["window_start"]
                == tomorrow.astimezone(UTC).isoformat()
            )
        forecast_coordinator = entry.runtime_data
        live_coordinator = entry.runtime_data.live
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert not live_coordinator._listeners
        assert not forecast_coordinator._listeners
