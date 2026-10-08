"""Current SHMÚ warning level (0–3)."""

from homeassistant.components.sensor import SensorEntity

from .warning_entity import WarningEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([WarningLevel(entry)])


class WarningLevel(WarningEntity, SensorEntity):
    _attr_translation_key = "warning_level"
    _attr_icon = "mdi:alert"

    def __init__(self, entry):
        super().__init__(entry, "warning_level")

    @property
    def native_value(self):
        return max((a["level"] for a in self.active), default=0)
