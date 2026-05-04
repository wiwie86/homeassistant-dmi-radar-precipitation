"""Sensor platform for DMI Radar Precipitation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.components.sensor.const import SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfLength, UnitOfVolumetricFlux
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import RadarSnapshot
from .const import ATTRIBUTION, DOMAIN
from .coordinator import DMIRadarPrecipitationCoordinator


@dataclass(frozen=True, kw_only=True)
class DMIRadarSensorDescription(SensorEntityDescription):
    """Describe a DMI radar precipitation sensor."""

    value_fn: Callable[[RadarSnapshot], Any]
    attributes_fn: Callable[[RadarSnapshot], dict[str, Any]]


def _common_attributes(snapshot: RadarSnapshot) -> dict[str, Any]:
    return {
        "attribution": ATTRIBUTION,
        "requested_latitude": snapshot.requested_latitude,
        "requested_longitude": snapshot.requested_longitude,
        "radar_latitude": snapshot.radar_point.latitude,
        "radar_longitude": snapshot.radar_point.longitude,
        "radar_row": snapshot.radar_point.row,
        "radar_column": snapshot.radar_point.column,
        "distance_from_target_km": round(snapshot.radar_point.distance_from_target_km, 3),
        "grid_spacing_m": snapshot.radar_point.grid_spacing_m,
        "history_coverage_start": snapshot.coverage_start.isoformat() if snapshot.coverage_start else None,
        "history_coverage_complete": snapshot.coverage_complete,
    }


def _latest_attributes(snapshot: RadarSnapshot) -> dict[str, Any]:
    attributes = _common_attributes(snapshot)
    latest = snapshot.latest
    if latest is not None:
        attributes.update(
            {
                "observed": latest.observed.isoformat(),
                "scan_type": latest.scan_type,
                "source_file": latest.filename,
                "dbz": latest.dbz,
                "raw_value": latest.raw_value,
            }
        )
    return attributes


def _aggregate_value(snapshot: RadarSnapshot, hours: int) -> float | None:
    if not snapshot.history:
        return None
    latest = snapshot.history[-1].observed
    cutoff = latest.timestamp() - hours * 3600
    values = [sample.estimated_mm for sample in snapshot.history if sample.observed.timestamp() > cutoff]
    if not values:
        return None
    return round(sum(values), 3)


def _aggregate_attributes(snapshot: RadarSnapshot, hours: int) -> dict[str, Any]:
    attributes = _common_attributes(snapshot)
    if snapshot.history:
        latest = snapshot.history[-1].observed
        cutoff = latest.timestamp() - hours * 3600
        relevant = [sample for sample in snapshot.history if sample.observed.timestamp() > cutoff]
        window_complete = bool(snapshot.coverage_start and snapshot.coverage_start <= latest - timedelta(hours=hours))
        attributes.update(
            {
                "window": f"{hours}h",
                "sample_count": len(relevant),
                "latest_sample": latest.isoformat(),
                "window_complete": window_complete,
                "history": [
                    {
                        "observed": sample.observed.isoformat(),
                        "mm": sample.estimated_mm,
                        "rain_rate_mm_per_hour": sample.rain_rate_mm_per_hour,
                    }
                    for sample in relevant
                ],
            }
        )
    return attributes


def _latest_observed(snapshot: RadarSnapshot) -> datetime | None:
    return snapshot.latest.observed if snapshot.latest is not None else None


def _distance_value(snapshot: RadarSnapshot) -> float:
    return round(snapshot.radar_point.distance_from_target_km, 3)


SENSOR_DESCRIPTIONS: tuple[DMIRadarSensorDescription, ...] = (
    DMIRadarSensorDescription(
        key="rain_rate",
        name="Rain Rate",
        icon="mdi:weather-rainy",
        device_class=SensorDeviceClass.PRECIPITATION_INTENSITY,
        native_unit_of_measurement=UnitOfVolumetricFlux.MILLIMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda snapshot: round(snapshot.latest.rain_rate_mm_per_hour, 3) if snapshot.latest else None,
        attributes_fn=_latest_attributes,
    ),
    DMIRadarSensorDescription(
        key="precipitation_past_hour",
        name="Precipitation Past Hour",
        icon="mdi:weather-pouring",
        native_unit_of_measurement=UnitOfLength.MILLIMETERS,
        suggested_display_precision=2,
        value_fn=lambda snapshot: _aggregate_value(snapshot, 1),
        attributes_fn=lambda snapshot: _aggregate_attributes(snapshot, 1),
    ),
    DMIRadarSensorDescription(
        key="precipitation_past_3_hours",
        name="Precipitation Past 3 Hours",
        icon="mdi:weather-pouring",
        native_unit_of_measurement=UnitOfLength.MILLIMETERS,
        suggested_display_precision=2,
        value_fn=lambda snapshot: _aggregate_value(snapshot, 3),
        attributes_fn=lambda snapshot: _aggregate_attributes(snapshot, 3),
    ),
    DMIRadarSensorDescription(
        key="precipitation_past_6_hours",
        name="Precipitation Past 6 Hours",
        icon="mdi:weather-pouring",
        native_unit_of_measurement=UnitOfLength.MILLIMETERS,
        suggested_display_precision=2,
        value_fn=lambda snapshot: _aggregate_value(snapshot, 6),
        attributes_fn=lambda snapshot: _aggregate_attributes(snapshot, 6),
    ),
    DMIRadarSensorDescription(
        key="precipitation_past_12_hours",
        name="Precipitation Past 12 Hours",
        icon="mdi:weather-pouring",
        native_unit_of_measurement=UnitOfLength.MILLIMETERS,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        value_fn=lambda snapshot: _aggregate_value(snapshot, 12),
        attributes_fn=lambda snapshot: _aggregate_attributes(snapshot, 12),
    ),
    DMIRadarSensorDescription(
        key="precipitation_past_24_hours",
        name="Precipitation Past 24 Hours",
        icon="mdi:weather-pouring",
        native_unit_of_measurement=UnitOfLength.MILLIMETERS,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        value_fn=lambda snapshot: _aggregate_value(snapshot, 24),
        attributes_fn=lambda snapshot: _aggregate_attributes(snapshot, 24),
    ),
    DMIRadarSensorDescription(
        key="latest_observed",
        name="Latest Observed",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_latest_observed,
        attributes_fn=_latest_attributes,
    ),
    DMIRadarSensorDescription(
        key="distance_to_radar_cell",
        name="Distance To Radar Cell",
        icon="mdi:map-marker-distance",
        native_unit_of_measurement="km",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_distance_value,
        attributes_fn=_latest_attributes,
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: DMIRadarPrecipitationCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(DMIRadarSensor(coordinator, description) for description in SENSOR_DESCRIPTIONS)


class DMIRadarSensor(CoordinatorEntity[DMIRadarPrecipitationCoordinator], SensorEntity):
    """Representation of a derived radar precipitation sensor."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DMIRadarPrecipitationCoordinator, description: DMIRadarSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{coordinator.config_entry.entry_id}_{description.key}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
            manufacturer="DMI",
            model="Radar Composite Derived Precipitation",
            name=self.coordinator.config_entry.title,
            configuration_url="https://www.dmi.dk/friedata/dokumentation/radar-data-api",
        )

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.entity_description.attributes_fn(self.coordinator.data)
