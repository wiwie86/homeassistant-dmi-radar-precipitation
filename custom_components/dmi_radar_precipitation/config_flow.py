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
from homeassistant.helpers.selector import BooleanSelector, NumberSelector, NumberSelectorConfig, NumberSelectorMode

from .api import DMIRadarClient, DMIRadarConnectionError
from .const import CONF_ENABLE_BACKFILL, CONF_SCAN_INTERVAL, DEFAULT_ENABLE_BACKFILL, DEFAULT_SCAN_INTERVAL, DOMAIN, MAX_SCAN_INTERVAL, MIN_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

ERROR_PLACEHOLDER_DEFAULT = "No additional details available."


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

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._error_detail = ERROR_PLACEHOLDER_DEFAULT

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return DMIRadarPrecipitationOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        placeholders = {"error_detail": self._error_detail}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except DMIRadarConnectionError as error:
                _LOGGER.warning("Radar config validation failed: %s", error)
                errors["base"] = "cannot_connect"
                self._error_detail = error.user_message
                placeholders["error_detail"] = self._error_detail
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected exception during radar validation")
                errors["base"] = "unknown"
                self._error_detail = "An unexpected error occurred. Check the Home Assistant log for the full stack trace."
                placeholders["error_detail"] = self._error_detail
            else:
                self._error_detail = ERROR_PLACEHOLDER_DEFAULT
                await self.async_set_unique_id(info["unique_id"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=user_input)

        defaults = {
            CONF_LATITUDE: self.hass.config.latitude,
            CONF_LONGITUDE: self.hass.config.longitude,
        }
        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(defaults),
            errors=errors,
            description_placeholders=placeholders,
        )


class DMIRadarPrecipitationOptionsFlow(config_entries.OptionsFlow):
    """Handle options for the radar integration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self._config_entry.options.get(
            CONF_SCAN_INTERVAL,
            self._config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        current_backfill = self._config_entry.options.get(
            CONF_ENABLE_BACKFILL,
            self._config_entry.data.get(CONF_ENABLE_BACKFILL, DEFAULT_ENABLE_BACKFILL),
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ENABLE_BACKFILL, default=current_backfill): BooleanSelector({}),
                    vol.Required(CONF_SCAN_INTERVAL, default=current_interval): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                    )
                }
            ),
        )
