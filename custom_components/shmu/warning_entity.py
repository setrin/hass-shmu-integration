"""Common warning entity behavior and age/validity checks."""

from datetime import UTC, datetime, timedelta

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_STATION, DOMAIN


class WarningEntity(CoordinatorEntity):
    """Warnings cover the selected city's district, not the observation station."""

    _attr_has_entity_name = True
    _attr_attribution = "Meteorological warnings by SHMÚ"

    def __init__(self, entry, suffix):
        super().__init__(entry.runtime_data.live)
        self._attr_unique_id = f"{entry.data[CONF_STATION]}_{suffix}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.data[CONF_STATION])})

    @property
    def snapshot(self):
        return (self.coordinator.data or {}).get("warnings")

    @property
    def available(self):
        return bool(
            super().available
            and self.snapshot
            and datetime.now(UTC) - datetime.fromisoformat(self.snapshot["checked_at"])
            <= timedelta(minutes=15)
        )

    @property
    def alerts(self):
        now = datetime.now(UTC)
        return [
            a
            for a in (self.snapshot or {}).get("alerts", [])
            if datetime.fromisoformat(a["ends_at"]) > now
        ]

    @property
    def active(self):
        now = datetime.now(UTC)
        return [a for a in self.alerts if datetime.fromisoformat(a["starts_at"]) <= now]

    @property
    def extra_state_attributes(self):
        snapshot = self.snapshot or {}
        return {
            "district": snapshot.get("district"),
            "source_url": snapshot.get("url"),
            "last_checked": snapshot.get("checked_at"),
            "active_warnings": self.active,
            "upcoming_warnings": [a for a in self.alerts if a not in self.active],
            "highest_upcoming_level": max(
                (a["level"] for a in self.alerts if a not in self.active), default=0
            ),
        }
