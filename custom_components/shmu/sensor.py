"""SHMÚ warning level, current weather and next-24-hour forecast extrema."""

from datetime import UTC, datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfSpeed, UnitOfTemperature
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_utc_time_change
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_STATION, DOMAIN
from .current import current_forecast, fresh_observation
from .forecast import next_24h_extreme
from .warning_entity import WarningEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [
            WarningLevel(entry),
            *[WeatherValue(entry, key, field, reduction) for key, field, reduction in VALUES],
        ]
    )


class WarningLevel(WarningEntity, SensorEntity):
    _attr_translation_key = "warning_level"
    _attr_icon = "mdi:alert"

    def __init__(self, entry):
        super().__init__(entry, "warning_level")

    @property
    def native_value(self):
        return max((a["level"] for a in self.active), default=0)


VALUES = (
    ("today_temperature_min", "native_temperature", "min"),
    ("today_temperature_max", "native_temperature", "max"),
    ("current_temperature", "native_temperature", None),
    ("current_wind", "native_wind_speed", None),
    ("current_gust", "native_wind_gust_speed", None),
    ("today_wind_min", "native_wind_speed", "min"),
    ("today_wind_max", "native_wind_speed", "max"),
    ("today_gust_min", "native_wind_gust_speed", "min"),
    ("today_gust_max", "native_wind_gust_speed", "max"),
)


class WeatherValue(CoordinatorEntity, SensorEntity):
    """Use the same current source and normalized hourly forecast as the weather entity."""

    _attr_has_entity_name = True
    _attr_attribution = "Weather data by SHMÚ"
    _attr_suggested_display_precision = 1

    def __init__(self, entry, key, field, reduction):
        super().__init__(entry.runtime_data)
        self.field = field
        self.reduction = reduction
        self._attr_unique_id = f"{entry.data[CONF_STATION]}_{key}"
        # Keep existing unique/entity IDs so watch complications and automations survive.
        self._attr_translation_key = key.replace("today_", "next_24h_", 1) if reduction else key
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.data[CONF_STATION])})
        temperature = field == "native_temperature"
        self._attr_device_class = (
            SensorDeviceClass.TEMPERATURE if temperature else SensorDeviceClass.WIND_SPEED
        )
        self._attr_native_unit_of_measurement = (
            UnitOfTemperature.CELSIUS if temperature else UnitOfSpeed.METERS_PER_SECOND
        )
        if reduction is None:
            self._attr_state_class = SensorStateClass.MEASUREMENT

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        if self.reduction is None:
            self.async_on_remove(
                self.coordinator.live.async_add_listener(self._handle_coordinator_update)
            )
        # Slide the 24-hour forecast window without waiting for a network refresh.
        self.async_on_remove(
            async_track_utc_time_change(self.hass, self._clock_update, minute=0, second=0)
        )

    @callback
    def _clock_update(self, now):
        self.async_write_ha_state()

    @property
    def summary(self):
        return next_24h_extreme(
            self.coordinator.data.hours if self.coordinator.data else {},
            self.field,
            self.reduction,
            datetime.now(UTC),
        )

    @property
    def observation(self):
        return fresh_observation(self.coordinator, datetime.now(UTC))

    @property
    def available(self):
        if self.reduction is None:
            return bool(self.observation) or (
                super().available and bool(current_forecast(self.coordinator, datetime.now(UTC)))
            )
        return super().available and self.summary["forecast_hours"] > 0

    @property
    def native_value(self):
        if self.reduction:
            return self.summary["value"]
        values = self.observation or current_forecast(self.coordinator, datetime.now(UTC))
        return values.get(self.field)

    @property
    def extra_state_attributes(self):
        if self.reduction:
            return {
                "source": "forecast_model",
                "forecast_mode": self.coordinator.mode,
                **{key: value for key, value in self.summary.items() if key != "value"},
            }
        observation = self.observation
        if observation:
            return {
                "source": "observation",
                "observation_station": observation.get("station"),
                "observation_time": observation.get("measured_at"),
                "observation_distance_km": observation.get("distance_km"),
            }
        row = current_forecast(self.coordinator, datetime.now(UTC))
        return {
            "source": "forecast_model",
            "model": row.get("model"),
            "forecast_time": row.get("datetime"),
        }
