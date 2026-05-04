"""Coordinator for DMI Radar Precipitation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DMIRadarClient, DMIRadarConnectionError, RadarScanSample, RadarSnapshot
from .const import BACKFILL_CHUNK_HOURS, CONF_ENABLE_BACKFILL, CONF_SCAN_INTERVAL, DEFAULT_ENABLE_BACKFILL, DEFAULT_NAME, DEFAULT_SCAN_INTERVAL, DOMAIN, HISTORY_HOURS, MIN_SCAN_INTERVAL

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
        self.enable_backfill = bool(config.get(CONF_ENABLE_BACKFILL, DEFAULT_ENABLE_BACKFILL))
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
                if self._history:
                    _LOGGER.info(
                        "Loaded %s cached radar scans for %.6f, %.6f with coverage from %s to %s",
                        len(self._history),
                        self.latitude,
                        self.longitude,
                        self._history[0].observed.isoformat(),
                        self._history[-1].observed.isoformat(),
                    )
                else:
                    _LOGGER.info(
                        "No cached radar history found for %.6f, %.6f; starting with a short recent fetch",
                        self.latitude,
                        self.longitude,
                    )
                    if not self.enable_backfill:
                        _LOGGER.info(
                            "Radar history backfill is disabled for %.6f, %.6f; only recent data will be kept current",
                            self.latitude,
                            self.longitude,
                        )

            result = await self.client.async_get_snapshot(
                self.latitude,
                self.longitude,
                existing_history=self._history,
            )
            if result.updated_history != self._history:
                new_samples = len(result.updated_history) - len(self._history)
                _LOGGER.info(
                    "Fetched %s new radar scans for %.6f, %.6f; coverage is now %s to %s",
                    new_samples,
                    self.latitude,
                    self.longitude,
                    result.updated_history[0].observed.isoformat(),
                    result.updated_history[-1].observed.isoformat(),
                )
            self._history = result.updated_history
            if self.enable_backfill:
                self._history = await self._async_backfill_history(self._history)
            await self._async_save_history(self._history)
            latest_observed = self._history[-1].observed if self._history else None
            coverage_complete = bool(
                self._history
                and latest_observed is not None
                and self._history[0].observed <= latest_observed - timedelta(hours=HISTORY_HOURS)
            )

            snapshot = RadarSnapshot(
                requested_latitude=result.snapshot.requested_latitude,
                requested_longitude=result.snapshot.requested_longitude,
                radar_point=result.snapshot.radar_point,
                latest=self._history[-1] if self._history else None,
                history=self._history,
                fetched_at=result.snapshot.fetched_at,
                coverage_start=self._history[0].observed if self._history else None,
                coverage_complete=coverage_complete,
            )
            if snapshot.coverage_complete:
                _LOGGER.info(
                    "Radar history backfill complete for %.6f, %.6f; 24h coverage starts at %s",
                    self.latitude,
                    self.longitude,
                    snapshot.coverage_start.isoformat() if snapshot.coverage_start else "unknown",
                )
            else:
                _LOGGER.info(
                    "Radar history %s for %.6f, %.6f; current coverage starts at %s",
                    "backfill still in progress" if self.enable_backfill else "coverage remains limited because backfill is disabled",
                    self.latitude,
                    self.longitude,
                    snapshot.coverage_start.isoformat() if snapshot.coverage_start else "unknown",
                )
            return snapshot
        except DMIRadarConnectionError as error:
            _LOGGER.warning("Radar update failed for %.6f, %.6f: %s", self.latitude, self.longitude, error)
            raise UpdateFailed(f"Could not fetch DMI radar data: {error}") from error

    async def _async_backfill_history(self, history: tuple[RadarScanSample, ...]) -> tuple[RadarScanSample, ...]:
        """Backfill older radar scans in small chunks after setup."""
        if not history:
            return history

        oldest = history[0].observed
        target_start = history[-1].observed - timedelta(hours=HISTORY_HOURS)
        if oldest <= target_start:
            return history

        _LOGGER.info(
            "Backfilling older radar scans for %.6f, %.6f from %s further back toward %s in %sh chunks",
            self.latitude,
            self.longitude,
            oldest.isoformat(),
            target_start.isoformat(),
            BACKFILL_CHUNK_HOURS,
        )

        result = await self.client.async_backfill_history(
            self.latitude,
            self.longitude,
            existing_history=history,
            backfill_hours=BACKFILL_CHUNK_HOURS,
            max_history_hours=HISTORY_HOURS,
        )

        if result.updated_history == history:
            _LOGGER.info(
                "No older radar scans were added during backfill for %.6f, %.6f; coverage remains %s",
                self.latitude,
                self.longitude,
                history[0].observed.isoformat(),
            )
            return history

        added_samples = len(result.updated_history) - len(history)
        _LOGGER.info(
            "Backfilled %s older radar scans for %.6f, %.6f; coverage moved from %s to %s",
            added_samples,
            self.latitude,
            self.longitude,
            history[0].observed.isoformat(),
            result.updated_history[0].observed.isoformat(),
        )

        return result.updated_history

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
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
