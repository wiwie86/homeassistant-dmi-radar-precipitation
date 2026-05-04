"""Config flow for DMI Radar Precipitation."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.selector import NumberSelector, NumberSelectorConfig, NumberSelectorMode

from .api import DMIRadarClient, DMIRadarConnectionError
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN, MAX_SCAN_INTERVAL, MIN_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


def _user_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_LATITUDE,
                default=defaults.get(CONF_LATITUDE),
            ): NumberSelector(
                NumberSelectorConfig(min=-90, max=90, step="any", mode=NumberSelectorMode.BOX)
            ),
            vol.Required(
                CONF_LONGITUDE,
                default=defaults.get(CONF_LONGITUDE),
            ): NumberSelector(
                NumberSelectorConfig(min=-180, max=180, step="any", mode=NumberSelectorMode.BOX)
            ),
        }
    )


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    client = DMIRadarClient(aiohttp_client.async_get_clientsession(hass))
    result = await client.async_get_snapshot(
        float(data[CONF_LATITUDE]),
        float(data[CONF_LONGITUDE]),
        max_history_hours=1,
    )
    snapshot = result.snapshot
    return {
        "title": f"Radar {data[CONF_LATITUDE]:.4f}, {data[CONF_LONGITUDE]:.4f}",
        "unique_id": f"{data[CONF_LATITUDE]:.4f}_{data[CONF_LONGITUDE]:.4f}",
        "resolved_latitude": snapshot.radar_point.latitude,
        "resolved_longitude": snapshot.radar_point.longitude,
    }


class DMIRadarPrecipitationConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow for DMI Radar Precipitation."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return DMIRadarPrecipitationOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except DMIRadarConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected exception during radar validation")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info["unique_id"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=user_input)

        defaults = {
            CONF_LATITUDE: self.hass.config.latitude,
            CONF_LONGITUDE: self.hass.config.longitude,
        }
        return self.async_show_form(step_id="user", data_schema=_user_schema(defaults), errors=errors)


class DMIRadarPrecipitationOptionsFlow(config_entries.OptionsFlow):
    """Handle options for the radar integration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL,
            self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current_interval): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                    )
                }
            ),
        )
