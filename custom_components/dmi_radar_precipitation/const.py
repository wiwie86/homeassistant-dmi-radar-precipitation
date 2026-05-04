"""Constants for the DMI Radar Precipitation integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "dmi_radar_precipitation"
PLATFORMS: list[Platform] = [Platform.SENSOR]

CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_SCAN_INTERVAL = 600
MIN_SCAN_INTERVAL = 300
MAX_SCAN_INTERVAL = 3600

DEFAULT_NAME = "DMI Radar Precipitation"
ATTRIBUTION = "Data provided by DMI Open Data Radar"

COLLECTION_COMPOSITE = "composite"
DEFAULT_LIMIT = 288
INITIAL_HISTORY_HOURS = 3
SCANS_PER_HOUR = 12
BACKFILL_CHUNK_HOURS = 24

RADAR_SCAN_MINUTES = 5
HISTORY_HOURS = 24 * 28
