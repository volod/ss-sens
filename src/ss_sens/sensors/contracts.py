"""Map LoRaWAN readings onto ss-common site-event contracts and MQTT topics."""

import json
import math
from datetime import UTC, datetime
from typing import Any

from ss_contracts.models import SensorEvent as SensorEventMessage
from ss_contracts.models import SensorReading as SensorReadingMessage
from ss_contracts.models import SensorState as SensorStateMessage
from ss_kit.mqtt import TopicBuilder

from ..mesh.site_state import SensorSummary
from .lorawan_decoder import SensorReading

# Sector grid resolution in degrees (~110 m per 0.001 deg).
_GRID_DEG = 0.001

_READING_FIELDS = (
    "temperature_c",
    "humidity_pct",
    "co2_ppm",
    "pressure_hpa",
    "battery_v",
)


def _payload_from_reading(reading: SensorReading) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for field in _READING_FIELDS:
        value = getattr(reading, field, None)
        if value is not None:
            payload[field] = value
    if reading.motion is not None:
        payload["motion"] = reading.motion
    if reading.rssi is not None:
        payload["rssi"] = reading.rssi
    if reading.snr is not None:
        payload["snr"] = reading.snr
    return payload


def sector_from_gps(lat: float | None, lon: float | None) -> str:
    """Map a GPS coordinate to a coarse grid sector ID."""
    if lat is None or lon is None:
        return "unknown"
    lat_cell = math.floor(lat / _GRID_DEG)
    lon_cell = math.floor(lon / _GRID_DEG)
    return f"grid:{lat_cell}:{lon_cell}"


def sensor_reading_to_event(
    reading: SensorReading,
    *,
    ingest_time: datetime | None = None,
) -> SensorEventMessage:
    """Convert a decoded LoRaWAN reading into a contract ``sensor-event``."""
    ingest = ingest_time or datetime.now(UTC)
    return SensorEventMessage(
        event_kind="sensor",
        event_time=reading.received_at,
        ingest_time=ingest,
        node_id=str(reading.dev_eui or "lorawan-unknown").strip().lower(),
        sensor_type="lorawan",
        sector_id=sector_from_gps(reading.gps_lat, reading.gps_lon),
        payload=_payload_from_reading(reading),
        freshness_sec=0.0,
    )


def reading_to_message(reading: SensorReading) -> SensorReadingMessage:
    """Validate a ``SensorReading`` as the ``sensor-reading`` contract message."""
    return SensorReadingMessage.model_validate(
        {
            "dev_eui": reading.dev_eui,
            "application_id": reading.application_id,
            "received_at": reading.received_at,
            "f_cnt": reading.f_cnt,
            "rssi": reading.rssi,
            "snr": reading.snr,
            "temperature_c": reading.temperature_c,
            "humidity_pct": reading.humidity_pct,
            "co2_ppm": reading.co2_ppm,
            "pressure_hpa": reading.pressure_hpa,
            "battery_v": reading.battery_v,
            "motion": reading.motion,
            "gps_lat": reading.gps_lat,
            "gps_lon": reading.gps_lon,
            "gps_alt_m": reading.gps_alt_m,
            "raw_bytes": reading.raw_bytes,
            "decoded_object": reading.decoded_object,
        }
    )


def summary_to_state(summary: SensorSummary) -> SensorStateMessage:
    """Validate a rolling-window summary as the retained ``sensor-state`` message."""
    return SensorStateMessage.model_validate(summary.model_dump())


def message_json(message: Any) -> bytes:
    """UTF-8 JSON for an MQTT payload; unset / null optional fields are omitted."""
    dumped = message.model_dump(mode="json", exclude_none=True)
    return json.dumps(dumped).encode("utf-8")


class ContractPublisher:
    """Publish sensor-reading, sensor-state, and sensor-event messages on the topic map."""

    def __init__(
        self, client: Any, topics: TopicBuilder | None = None, site_id: str = "local"
    ) -> None:
        self._client = client
        self._topics = topics if topics is not None else TopicBuilder()
        self._site_id = site_id

    async def publish_reading(self, reading: SensorReading) -> str:
        topic = self._topics.build("sensor-reading", site_id=self._site_id, dev_eui=reading.dev_eui)
        await self._client.publish(topic, payload=message_json(reading_to_message(reading)), qos=1)
        return topic

    async def publish_state(self, summary: SensorSummary) -> str:
        topic = self._topics.build("sensor-state", site_id=self._site_id, dev_eui=summary.dev_eui)
        await self._client.publish(
            topic, payload=message_json(summary_to_state(summary)), qos=1, retain=True
        )
        return topic

    async def publish_sensor_event(
        self,
        reading: SensorReading,
        *,
        ingest_time: datetime | None = None,
    ) -> str:
        event = sensor_reading_to_event(reading, ingest_time=ingest_time)
        topic = self._topics.build("sensor-event", site_id=self._site_id, node_id=event.node_id)
        await self._client.publish(topic, payload=message_json(event), qos=1)
        return topic

    async def publish_from_reading(
        self, reading: SensorReading, summary: SensorSummary | None
    ) -> None:
        """Publish the three contract messages that follow one uplink."""
        await self.publish_reading(reading)
        if summary is not None:
            await self.publish_state(summary)
        await self.publish_sensor_event(reading)
