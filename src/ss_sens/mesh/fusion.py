"""Sensor mesh fusion — GPS-proximity neighbour links between LoRaWAN nodes.

The SensorMeshFusion class is stateless: it accepts a SiteStateAggregator and
produces a mesh snapshot on demand for GET /site/mesh.
"""

import math
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from ..sensors.lorawan_decoder import SensorReading
from .site_state import SiteState, SiteStateAggregator


class MeshNode(BaseModel):
    """Single node in the site sensor mesh."""

    node_id: str
    node_type: str  # "sensor"
    lat: float | None = None
    lon: float | None = None
    alt_m: float | None = None
    last_updated: datetime
    attributes: dict[str, Any] = Field(default_factory=dict)
    neighbor_ids: list[str] = Field(default_factory=list)


class SiteMesh(BaseModel):
    """Point-in-time snapshot of the sensor mesh."""

    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    nodes: list[MeshNode] = Field(default_factory=list)
    edge_count: int = 0


class SensorMeshFusion:
    """Build a spatial mesh from LoRaWAN sensor streams.

    Args:
        aggregator: SiteStateAggregator that holds current sensor readings.
        proximity_radius_m: Maximum distance (metres) between two GPS-positioned
                            nodes for them to be considered neighbours.
    """

    def __init__(
        self,
        aggregator: SiteStateAggregator,
        proximity_radius_m: float = 100.0,
    ) -> None:
        self._aggregator = aggregator
        self._proximity_m = proximity_radius_m

    async def get_mesh(self) -> SiteMesh:
        """Produce a current snapshot of the site mesh."""
        state: SiteState = await self._aggregator.get_state()
        nodes: list[MeshNode] = []

        for sensor in state.sensors:
            nodes.append(
                MeshNode(
                    node_id=f"sensor:{sensor.dev_eui}",
                    node_type="sensor",
                    lat=sensor.gps_lat,
                    lon=sensor.gps_lon,
                    alt_m=sensor.gps_alt_m,
                    last_updated=sensor.last_seen,
                    attributes=_sensor_attrs(sensor),
                )
            )

        _link_neighbours(nodes, self._proximity_m)
        edge_count = sum(len(n.neighbor_ids) for n in nodes) // 2

        return SiteMesh(nodes=nodes, edge_count=edge_count)

    def node_from_sensor_reading(self, reading: SensorReading) -> MeshNode:
        return MeshNode(
            node_id=f"sensor:{reading.dev_eui}",
            node_type="sensor",
            lat=reading.gps_lat,
            lon=reading.gps_lon,
            alt_m=reading.gps_alt_m,
            last_updated=reading.received_at,
            attributes={
                "temperature_c": reading.temperature_c,
                "humidity_pct": reading.humidity_pct,
                "co2_ppm": reading.co2_ppm,
                "motion": reading.motion,
                "rssi": reading.rssi,
            },
        )


def _sensor_attrs(sensor: Any) -> dict[str, Any]:
    return {
        k: v
        for k, v in {
            "temperature_c": sensor.temperature_c,
            "humidity_pct": sensor.humidity_pct,
            "co2_ppm": sensor.co2_ppm,
            "pressure_hpa": sensor.pressure_hpa,
            "battery_v": sensor.battery_v,
            "motion": sensor.motion,
            "rssi": sensor.rssi,
            "snr": sensor.snr,
            "reading_count": sensor.reading_count,
        }.items()
        if v is not None
    }


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _link_neighbours(nodes: list[MeshNode], radius_m: float) -> None:
    positioned = [n for n in nodes if n.lat is not None and n.lon is not None]
    for i, first in enumerate(positioned):
        for second in positioned[i + 1 :]:
            dist = _haversine_m(first.lat, first.lon, second.lat, second.lon)  # type: ignore[arg-type]
            if dist <= radius_m:
                first.neighbor_ids.append(second.node_id)
                second.neighbor_ids.append(first.node_id)
