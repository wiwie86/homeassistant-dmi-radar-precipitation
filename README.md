# DMI Radar Precipitation for Home Assistant

Home Assistant custom integration for deriving local precipitation from DMI radar HDF5 composites.

[![Open your Home Assistant instance and open the custom repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=wiwie86&repository=homeassistant-dmi-radar-precipitation&category=integration)

What it does:
- lets you configure latitude and longitude from the Home Assistant UI
- downloads recent DMI radar composite files and samples the nearest radar grid cell
- converts radar reflectivity to estimated rain rate using the Z-R relation embedded in the file
- exposes sensors for current rain rate and derived precipitation sums over recent time windows
- exposes fixed midnight-aligned precipitation buckets for 10 min, 20 min, 30 min, 1h, 2h, 3h, 4h, 6h, 12h, and 24h charting
- stores only compact per-scan derived values locally and fetches only new radar scans after the initial backfill
- keeps setup validation lightweight by probing only a short recent radar window during config flow
- backfills older radar history gradually after setup so 24-hour totals become complete without blocking configuration

Important limitations:
- this is a draft approximation based on radar reflectivity, not gauge-corrected rain measurements
- the current implementation uses DMI composite radar scans and samples the nearest grid cell
- solid precipitation and beam-blocking effects can make the estimate less reliable than station observations

Requirements:
- Home Assistant `2025.1.0` or newer

HACS installation:
1. Open HACS and add `https://github.com/wiwie86/homeassistant-dmi-radar-precipitation` as a custom repository of type `Integration`.
2. Install `DMI Radar Precipitation` from HACS.
3. Restart Home Assistant.
4. Add the integration from `Settings -> Devices & Services`.

Project layout:
- `custom_components/dmi_radar_precipitation/` contains the integration code

Local installation:
1. Copy the integration folder into your Home Assistant config:

```bash
cp -r custom_components/dmi_radar_precipitation /config/custom_components/
```

2. Restart Home Assistant.
3. Go to `Settings -> Devices & Services -> Add Integration`.
4. Search for `DMI Radar Precipitation`.
5. Enter latitude and longitude for the point you want to estimate rainfall at.

Notes:
- uses the DMI Radar Data API at `opendataapi.dmi.dk`
- polling defaults to 600 seconds and is clamped to a minimum of 300 seconds
- history-based sensors are built from downloaded recent radar scans, not from station measurements
