"""Constants for the DMI Radar Precipitation integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "dmi_radar_precipitation"
PLATFORMS: list[Platform] = [Platform.SENSOR]

EVENT_RAIN_STARTED = f"{DOMAIN}_rain_started"
EVENT_RAIN_STOPPED = f"{DOMAIN}_rain_stopped"

CONF_ENABLE_BACKFILL = "enable_backfill"
CONF_HEAVY_RAIN_THRESHOLD = "heavy_rain_threshold"
CONF_LIGHT_RAIN_THRESHOLD = "light_rain_threshold"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_ENABLE_BACKFILL = False
DEFAULT_HEAVY_RAIN_THRESHOLD = 4.0
DEFAULT_LIGHT_RAIN_THRESHOLD = 0.1
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

RAIN_INTENSITY_NO_RAIN = "no_rain"
RAIN_INTENSITY_LIGHT_RAIN = "light_rain"
RAIN_INTENSITY_HEAVY_RAIN = "heavy_rain"
RAIN_INTENSITY_OPTIONS = [
    RAIN_INTENSITY_NO_RAIN,
    RAIN_INTENSITY_LIGHT_RAIN,
    RAIN_INTENSITY_HEAVY_RAIN,
]
