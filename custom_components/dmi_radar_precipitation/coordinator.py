"""Coordinator for DMI Radar Precipitation."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DMIRadarClient, DMIRadarConnectionError, RadarScanSample, RadarSnapshot
from .const import CONF_SCAN_INTERVAL, DEFAULT_NAME, DEFAULT_SCAN_INTERVAL, DOMAIN, MIN_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)
STORAGE_VERSION = 1


class DMIRadarPrecipitationCoordinator(DataUpdateCoordinator[RadarSnapshot]):
    """Coordinate DMI radar downloads and derived precipitation state."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.config_entry = entry
        config = {**entry.data, **entry.options}
        self.latitude = float(config["latitude"])
        self.longitude = float(config["longitude"])
        self.client = DMIRadarClient(aiohttp_client.async_get_clientsession(hass))
        self.store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._history: tuple[RadarScanSample, ...] = ()

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=entry.title or DEFAULT_NAME,
            update_interval=timedelta(
                seconds=max(
                    int(config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
                    MIN_SCAN_INTERVAL,
                )
            ),
        )

    async def _async_update_data(self) -> RadarSnapshot:
        try:
            if not self._history:
                self._history = await self._async_load_history()

            result = await self.client.async_get_snapshot(
                self.latitude,
                self.longitude,
                existing_history=self._history,
            )
            self._history = result.updated_history
            await self._async_save_history(self._history)
            return result.snapshot
        except DMIRadarConnectionError as error:
            _LOGGER.warning("Radar update failed for %.6f, %.6f: %s", self.latitude, self.longitude, error)
            raise UpdateFailed(f"Could not fetch DMI radar data: {error}") from error

    async def _async_load_history(self) -> tuple[RadarScanSample, ...]:
        """Load cached scan samples from Home Assistant storage."""
        stored = await self.store.async_load()
        if not stored:
            return ()

        history: list[RadarScanSample] = []
        for item in stored.get("history", []):
            history.append(
                RadarScanSample(
                    filename=item["filename"],
                    observed=_parse_datetime(item["observed"]),
                    created=_parse_datetime(item.get("created")),
                    scan_type=item.get("scan_type"),
                    raw_value=item.get("raw_value"),
                    dbz=item.get("dbz"),
                    rain_rate_mm_per_hour=float(item["rain_rate_mm_per_hour"]),
                    estimated_mm=float(item["estimated_mm"]),
                )
            )

        history.sort(key=lambda sample: sample.observed)
        return tuple(history)

    async def _async_save_history(self, history: tuple[RadarScanSample, ...]) -> None:
        """Persist compact derived radar history to Home Assistant storage."""
        await self.store.async_save(
            {
                "history": [
                    {
                        "filename": sample.filename,
                        "observed": sample.observed.isoformat(),
                        "created": sample.created.isoformat() if sample.created else None,
                        "scan_type": sample.scan_type,
                        "raw_value": sample.raw_value,
                        "dbz": sample.dbz,
                        "rain_rate_mm_per_hour": sample.rain_rate_mm_per_hour,
                        "estimated_mm": sample.estimated_mm,
                    }
                    for sample in history
                ]
            }
        )


def _parse_datetime(value: str | None):
    """Parse an ISO datetime from storage."""
    if value is None:
        return None
    from datetime import datetime

    return datetime.fromisoformat(value)
