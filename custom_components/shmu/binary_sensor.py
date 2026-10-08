"""A warning is on when an active or upcoming district warning exists."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity

from .warning_entity import WarningEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([WeatherWarning(entry)])


class WeatherWarning(WarningEntity, BinarySensorEntity):
    _attr_translation_key = "weather_warning"
    _attr_device_class = BinarySensorDeviceClass.SAFETY

    def __init__(self, entry):
        super().__init__(entry, "weather_warning")

    @property
    def is_on(self):
        return bool(self.alerts)
