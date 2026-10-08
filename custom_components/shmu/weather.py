"""Home Assistant weather entity with hourly and daily forecasts."""

from datetime import UTC, datetime

from astral import Observer
from astral.sun import elevation
from homeassistant.components.weather import WeatherEntity, WeatherEntityFeature
from homeassistant.const import UnitOfLength, UnitOfPressure, UnitOfSpeed, UnitOfTemperature
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_STATION, DOMAIN
from .forecast import condition, daily_forecasts, day_coverage


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ShmuWeather(entry.runtime_data, entry)])


class ShmuWeather(CoordinatorEntity, WeatherEntity):
    """Modeled current weather, not a station observation."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_attribution = "Forecast data by SHMÚ (Slovenský hydrometeorologický ústav)"
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_wind_speed_unit = UnitOfSpeed.METERS_PER_SECOND
    _attr_native_precipitation_unit = UnitOfLength.MILLIMETERS
    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_HOURLY | WeatherEntityFeature.FORECAST_DAILY
    )

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.data[CONF_STATION]}_weather"
        self._observer = Observer(entry.data["latitude"], entry.data["longitude"])
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data[CONF_STATION])},
            name=f"SHMÚ {entry.title}",
            manufacturer="SHMÚ",
            model="Numerical weather forecast",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=f"https://www.shmu.sk/sk/?page=2673&nwp_mesto={entry.data[CONF_STATION]}",
        )

    @property
    def _current(self):
        timestamp = int(datetime.now(UTC).timestamp()) // 3600 * 3600
        return self.coordinator.data.hours.get(timestamp, {}) if self.coordinator.data else {}

    @property
    def available(self):
        return super().available and bool(self._current)

    @property
    def native_temperature(self):
        return self._current.get("native_temperature")

    @property
    def native_pressure(self):
        return self._current.get("native_pressure")

    @property
    def native_wind_speed(self):
        return self._current.get("native_wind_speed")

    @property
    def native_wind_gust_speed(self):
        return self._current.get("native_wind_gust_speed")

    @property
    def wind_bearing(self):
        return self._current.get("wind_bearing")

    @property
    def cloud_coverage(self):
        return self._current.get("cloud_coverage")

    @property
    def condition(self):
        return condition(self._current, elevation(self._observer, datetime.now(UTC)) > 0)

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data
        if not data:
            return {}
        return {
            "current_weather_source": "forecast_model",
            "forecast_mode": self.coordinator.mode,
            "current_model": self._current.get("model"),
            "current_forecast_time": self._current.get("datetime"),
            "model_runs": {key: run.initialized.isoformat() for key, run in data.runs.items()},
            "degraded_models": data.degraded_models,
            "hourly_values_interpolated": "ecmwf" in data.runs,
            "forecast_day_coverage": day_coverage(data.hours, datetime.now(UTC)),
            "aladin_forecast_end": (
                datetime.fromtimestamp(max(data.runs["aladin"].hours) + 3600, UTC).isoformat()
                if "aladin" in data.runs
                else None
            ),
        }

    @callback
    def _handle_coordinator_update(self):
        super()._handle_coordinator_update()
        self.hass.async_create_task(self.async_update_listeners(None))

    async def async_forecast_hourly(self):
        now = int(datetime.now(UTC).timestamp()) // 3600 * 3600
        result = []
        for timestamp, record in self.coordinator.data.hours.items():
            if timestamp < now:
                continue
            item = {k: v for k, v in record.items() if k not in ("model", "snowfall")}
            dt = datetime.fromtimestamp(timestamp, UTC)
            if icon := condition(record, elevation(self._observer, dt) > 0):
                item["condition"] = icon
            result.append(item)
        return result

    async def async_forecast_daily(self):
        return daily_forecasts(self.coordinator.data.hours, datetime.now(UTC))
