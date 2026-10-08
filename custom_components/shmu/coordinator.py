"""Coordinate SHMÚ data and keep modeled current conditions advancing."""

import logging
from datetime import timedelta

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ShmuClient, ShmuError
from .const import CONF_MODE, CONF_STATION, DEFAULT_MODE, DOMAIN

_LOGGER = logging.getLogger(__name__)


class ShmuCoordinator(DataUpdateCoordinator):
    """Check published runs every 30 minutes; cached run JSON is reused."""

    def __init__(self, hass, entry):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(minutes=30),
        )
        self.client = ShmuClient(async_get_clientsession(hass), entry.data[CONF_STATION])
        self.mode = entry.options.get(CONF_MODE, entry.data.get(CONF_MODE, DEFAULT_MODE))

    async def _async_update_data(self):
        try:
            return await self.client.fetch(self.mode)
        except ShmuError as err:
            raise UpdateFailed(str(err)) from err
