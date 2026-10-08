"""SHMÚ weather forecasts for Slovakia."""

from homeassistant.const import Platform

from .coordinator import ShmuCoordinator

PLATFORMS = [Platform.WEATHER]


async def async_setup_entry(hass, entry):
    """Set up one city from the UI."""
    coordinator = ShmuCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_reload_entry(hass, entry):
    """Apply options by reloading the entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    """Unload the weather platform and its coordinator listeners."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
