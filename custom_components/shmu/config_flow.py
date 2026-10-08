"""Searchable SHMÚ city selection and forecast-model options."""

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectSelectorMode

from .api import ShmuClient, ShmuError
from .const import CONF_MODE, CONF_STATION, DEFAULT_MODE, DOMAIN, MODES


def mode_selector():
    return SelectSelector(SelectSelectorConfig(options=list(MODES), translation_key=CONF_MODE))


class ShmuConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Create a single entry per city."""

    VERSION = 1

    def __init__(self):
        self._stations = {}

    async def async_step_user(self, user_input=None):
        errors = {}
        client = ShmuClient(async_get_clientsession(self.hass), "32397")
        if not self._stations:
            try:
                self._stations = await client.stations()
            except ShmuError:
                return self.async_show_form(
                    step_id="user", data_schema=vol.Schema({}), errors={"base": "cannot_connect"}
                )
        if user_input and CONF_STATION in user_input:
            station_id = user_input[CONF_STATION]
            if station_id not in self._stations:
                errors[CONF_STATION] = "invalid_station"
            else:
                await self.async_set_unique_id(station_id)
                self._abort_if_unique_id_configured()
                try:
                    await ShmuClient(async_get_clientsession(self.hass), station_id).fetch(
                        user_input[CONF_MODE]
                    )
                except ShmuError:
                    errors["base"] = "cannot_connect"
                else:
                    return self.async_create_entry(
                        title=self._stations[station_id]["name"],
                        data={**self._stations[station_id], CONF_MODE: user_input[CONF_MODE]},
                    )
        choices = [
            {"value": key, "label": f"{row['name']} ({key})"}
            for key, row in sorted(self._stations.items(), key=lambda item: item[1]["name"])
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_STATION, default="32397"): SelectSelector(
                    SelectSelectorConfig(
                        options=choices,
                        mode=SelectSelectorMode.DROPDOWN,
                        custom_value=False,
                    )
                ),
                vol.Required(CONF_MODE, default=DEFAULT_MODE): mode_selector(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return ShmuOptionsFlow()


class ShmuOptionsFlow(config_entries.OptionsFlow):
    """Change the model strategy without adding a duplicate city."""

    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                await ShmuClient(
                    async_get_clientsession(self.hass),
                    self.config_entry.data[CONF_STATION],
                ).fetch(user_input[CONF_MODE])
            except ShmuError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title="", data=user_input)
        mode = self.config_entry.options.get(
            CONF_MODE,
            self.config_entry.data.get(CONF_MODE, DEFAULT_MODE),
        )
        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=vol.Schema({vol.Required(CONF_MODE, default=mode): mode_selector()}),
        )
