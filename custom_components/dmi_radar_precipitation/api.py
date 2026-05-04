"""API client and radar processing for DMI radar precipitation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
import math
from typing import Any

import h5py
from aiohttp import ClientError, ClientResponseError, ClientSession, ClientTimeout
from pyproj import CRS, Transformer

from .const import COLLECTION_COMPOSITE, DEFAULT_LIMIT, HISTORY_HOURS, INITIAL_HISTORY_HOURS, SCANS_PER_HOUR

BASE_URL = "https://opendataapi.dmi.dk/v1/radardata"
REQUEST_TIMEOUT = ClientTimeout(total=60)


class DMIRadarError(Exception):
    """Base exception for DMI radar errors."""


class DMIRadarConnectionError(DMIRadarError):
    """Raised when the radar API cannot be reached."""

    def __init__(self, message: str, user_message: str | None = None) -> None:
        """Initialize the exception with internal and user-facing messages."""
        super().__init__(message)
        self.user_message = user_message or message


@dataclass(slots=True)
class RadarScanSample:
    """One sampled radar scan at a target point."""

    filename: str
    observed: datetime
    created: datetime | None
    scan_type: str | None
    raw_value: int | None
    dbz: float | None
    rain_rate_mm_per_hour: float
    estimated_mm: float


@dataclass(slots=True)
class RadarPoint:
    """Details about the resolved radar point."""

    latitude: float
    longitude: float
    row: int
    column: int
    grid_spacing_m: float
    distance_from_target_km: float


@dataclass(slots=True)
class RadarSnapshot:
    """Combined radar snapshot and recent history."""

    requested_latitude: float
    requested_longitude: float
    radar_point: RadarPoint
    latest: RadarScanSample | None
    history: tuple[RadarScanSample, ...]
    fetched_at: datetime
    coverage_start: datetime | None
    coverage_complete: bool


@dataclass(slots=True)
class RadarFetchResult:
    """Result from fetching and merging radar data."""

    snapshot: RadarSnapshot
    updated_history: tuple[RadarScanSample, ...]


class DMIRadarClient:
    """Fetch and process radar composites from DMI."""

    def __init__(self, session: ClientSession) -> None:
        self._session = session
        self._point_cache: dict[str, RadarPoint] = {}

    async def async_get_snapshot(
        self,
        latitude: float,
        longitude: float,
        existing_history: tuple[RadarScanSample, ...] = (),
        max_history_hours: int = HISTORY_HOURS,
    ) -> RadarFetchResult:
        """Fetch only new radar scans and merge them with local history."""
        end = datetime.now(tz=UTC).replace(microsecond=0)
        history_hours = max_history_hours if existing_history else INITIAL_HISTORY_HOURS
        start = end - timedelta(hours=history_hours)
        latest_known = existing_history[-1].observed if existing_history else None
        query_start = latest_known + timedelta(seconds=1) if latest_known else start
        limit = DEFAULT_LIMIT if existing_history else history_hours * SCANS_PER_HOUR + 6
        return await self._async_fetch_and_merge(
            latitude,
            longitude,
            existing_history,
            query_start,
            end,
            limit,
            start,
        )

    async def async_backfill_history(
        self,
        latitude: float,
        longitude: float,
        existing_history: tuple[RadarScanSample, ...],
        backfill_hours: int,
        max_history_hours: int = HISTORY_HOURS,
    ) -> RadarFetchResult:
        """Fetch one older history chunk before the currently cached oldest sample."""
        if not existing_history:
            return await self.async_get_snapshot(
                latitude,
                longitude,
                existing_history=existing_history,
                max_history_hours=max_history_hours,
            )

        reference_end = existing_history[-1].observed
        target_start = reference_end - timedelta(hours=max_history_hours)
        oldest_known = existing_history[0].observed
        if oldest_known <= target_start:
            snapshot = RadarSnapshot(
                requested_latitude=latitude,
                requested_longitude=longitude,
                radar_point=self._point_cache.get(_point_cache_key(latitude, longitude))
                or RadarPoint(latitude, longitude, 0, 0, 500.0, 0.0),
                latest=existing_history[-1],
                history=existing_history,
                fetched_at=datetime.now(tz=UTC),
                coverage_start=existing_history[0].observed,
                coverage_complete=True,
            )
            return RadarFetchResult(snapshot=snapshot, updated_history=existing_history)

        chunk_end = oldest_known - timedelta(seconds=1)
        chunk_start = max(target_start, oldest_known - timedelta(hours=backfill_hours))
        limit = backfill_hours * SCANS_PER_HOUR + 6

        return await self._async_fetch_and_merge(
            latitude,
            longitude,
            existing_history,
            chunk_start,
            chunk_end,
            limit,
            target_start,
        )

    async def _async_fetch_and_merge(
        self,
        latitude: float,
        longitude: float,
        existing_history: tuple[RadarScanSample, ...],
        query_start: datetime,
        query_end: datetime,
        limit: int,
        trim_start: datetime,
    ) -> RadarFetchResult:
        """Fetch a time window of radar scans and merge them with cached history."""
        payload = await self._async_get_json(
            f"collections/{COLLECTION_COMPOSITE}/items",
            {
                "datetime": f"{_format_datetime(query_start)}/{_format_datetime(query_end)}",
                "sortorder": "datetime,DESC",
                "limit": str(limit),
            },
        )

        features = payload.get("features", [])

        samples = list(existing_history)
        seen_timestamps = {sample.observed for sample in existing_history}
        radar_point: RadarPoint | None = self._point_cache.get(_point_cache_key(latitude, longitude))

        for feature in features:
            sample, current_point = await self._async_sample_feature(
                feature,
                latitude,
                longitude,
            )
            if sample.observed not in seen_timestamps:
                samples.append(sample)
                seen_timestamps.add(sample.observed)
            if radar_point is None:
                radar_point = current_point

        if not samples:
            raise DMIRadarConnectionError(
                "No radar composites were returned by DMI",
                "No recent radar scans were available for the selected location and time window.",
            )

        samples = [sample for sample in samples if sample.observed >= trim_start]
        samples.sort(key=lambda sample: sample.observed)

        now = datetime.now(tz=UTC)
        latest_observed = samples[-1].observed
        target_start = latest_observed - timedelta(hours=HISTORY_HOURS)

        snapshot = RadarSnapshot(
            requested_latitude=latitude,
            requested_longitude=longitude,
            radar_point=radar_point or RadarPoint(latitude, longitude, 0, 0, 500.0, 0.0),
            latest=samples[-1] if samples else None,
            history=tuple(samples),
            fetched_at=now,
            coverage_start=samples[0].observed if samples else None,
            coverage_complete=bool(samples and samples[0].observed <= target_start),
        )
        self._point_cache[_point_cache_key(latitude, longitude)] = snapshot.radar_point
        return RadarFetchResult(snapshot=snapshot, updated_history=tuple(samples))

    async def _async_sample_feature(
        self,
        feature: dict[str, Any],
        latitude: float,
        longitude: float,
    ) -> tuple[RadarScanSample, RadarPoint]:
        """Download one HDF5 composite and sample it at the requested point."""
        url = feature["asset"]["data"]["href"]
        content = await self._async_get_bytes(url)

        with h5py.File(BytesIO(content), "r") as hdf5_file:
            data = hdf5_file["dataset1/data1/data"][:]
            what = hdf5_file["what"].attrs
            where = hdf5_file["where"].attrs
            how = hdf5_file["how"].attrs

            point = _resolve_radar_point(where, latitude, longitude)
            raw_value = int(data[point.row, point.column])
            nodata = int(what["nodata"])
            undetect = float(what["undetect"])

            dbz: float | None = None
            rain_rate = 0.0
            raw: int | None = raw_value

            if raw_value == nodata:
                raw = None
            elif float(raw_value) == undetect:
                rain_rate = 0.0
                dbz = None
            else:
                gain = float(what["gain"])
                offset = float(what["offset"])
                dbz = offset + raw_value * gain
                rain_rate = _dbz_to_rain_rate(dbz, float(how["zr-a"][0]), float(how["zr-b"][0]))

            return (
                RadarScanSample(
                    filename=feature["id"],
                    observed=_parse_datetime(feature["properties"]["datetime"]),
                    created=_parse_datetime(feature["properties"].get("created")),
                    scan_type=feature["properties"].get("scanType"),
                    raw_value=raw,
                    dbz=dbz,
                    rain_rate_mm_per_hour=rain_rate,
                    estimated_mm=rain_rate * (5.0 / 60.0),
                ),
                point,
            )

    async def _async_get_json(self, endpoint: str, params: dict[str, str]) -> dict[str, Any]:
        """Fetch JSON from DMI Radar API."""
        url = f"{BASE_URL}/{endpoint}"
        try:
            async with self._session.get(url, params=params, timeout=REQUEST_TIMEOUT) as response:
                response.raise_for_status()
                return await response.json()
        except ClientResponseError as error:
            raise DMIRadarConnectionError(
                f"Unexpected radar API response: HTTP {error.status}",
                f"DMI Radar API returned HTTP {error.status} while listing radar scans.",
            ) from error
        except ClientError as error:
            raise DMIRadarConnectionError(
                f"Failed to reach DMI Radar API: {error}",
                f"Could not reach DMI Radar API while listing radar scans: {error}",
            ) from error

    async def _async_get_bytes(self, url: str) -> bytes:
        """Download a radar file."""
        try:
            async with self._session.get(url, timeout=REQUEST_TIMEOUT) as response:
                response.raise_for_status()
                return await response.read()
        except ClientResponseError as error:
            raise DMIRadarConnectionError(
                f"Unexpected radar file response: HTTP {error.status}",
                f"DMI Radar API returned HTTP {error.status} while downloading a radar file.",
            ) from error
        except ClientError as error:
            raise DMIRadarConnectionError(
                f"Failed to download radar file: {error}",
                f"Could not download a radar HDF5 file from DMI: {error}",
            ) from error


def _resolve_radar_point(where: Any, latitude: float, longitude: float) -> RadarPoint:
    """Resolve the nearest radar grid cell for a target coordinate."""
    transformer = Transformer.from_crs("EPSG:4326", CRS.from_proj4(where["projdef"].decode()), always_xy=True)
    x, y = transformer.transform(longitude, latitude)

    ll_x, ll_y = transformer.transform(float(where["LL_lon"][0]), float(where["LL_lat"][0]))
    ul_x, ul_y = transformer.transform(float(where["UL_lon"][0]), float(where["UL_lat"][0]))

    xscale = float(where["xscale"])
    yscale = float(where["yscale"])
    columns = int(round((float(transformer.transform(float(where["LR_lon"][0]), float(where["LR_lat"][0]))[0]) - ll_x) / xscale)) + 1
    rows = int(round((ul_y - ll_y) / yscale)) + 1

    column = int(round((x - ll_x) / xscale))
    row = int(round((ul_y - y) / yscale))

    column = max(0, min(column, columns - 1))
    row = max(0, min(row, rows - 1))

    cell_x = ll_x + column * xscale
    cell_y = ul_y - row * yscale
    reverse = Transformer.from_crs(CRS.from_proj4(where["projdef"].decode()), "EPSG:4326", always_xy=True)
    cell_lon, cell_lat = reverse.transform(cell_x, cell_y)

    return RadarPoint(
        latitude=cell_lat,
        longitude=cell_lon,
        row=row,
        column=column,
        grid_spacing_m=xscale,
        distance_from_target_km=_haversine_km(latitude, longitude, cell_lat, cell_lon),
    )


def _dbz_to_rain_rate(dbz: float, zr_a: float, zr_b: float) -> float:
    """Convert reflectivity dBZ to rain rate mm/h using Z-R relation."""
    z = 10 ** (dbz / 10)
    return float((z / zr_a) ** (1 / zr_b))


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse an ISO datetime."""
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _format_datetime(value: datetime) -> str:
    """Format datetime for the radar API."""
    return value.isoformat().replace("+00:00", "Z")


def _haversine_km(latitude_1: float, longitude_1: float, latitude_2: float, longitude_2: float) -> float:
    """Calculate great-circle distance."""
    radius_km = 6371.0
    lat1 = math.radians(latitude_1)
    lon1 = math.radians(longitude_1)
    lat2 = math.radians(latitude_2)
    lon2 = math.radians(longitude_2)
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _point_cache_key(latitude: float, longitude: float) -> str:
    """Return a stable cache key for a requested point."""
    return f"{latitude:.6f}_{longitude:.6f}"
