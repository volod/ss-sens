"""Sensor rolling-window aggregator for the ss-sens service.

SiteStateAggregator maintains a rolling window of LoRaWAN sensor readings. It is
the source of truth for GET /site/sensors. Combined camera + sensor snapshots
live on the video API.

Thread-safe: all mutations go through an asyncio.Lock.
"""

import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field

from ..config import settings
from ..sensors.lorawan_decoder import SensorReading


class SensorSummary(BaseModel):
    """Aggregated summary of recent readings from one LoRaWAN device."""

    dev_eui: str
    last_seen: datetime
    reading_count: int
    temperature_c: float | None = None
    humidity_pct: float | None = None
    co2_ppm: float | None = None
    pressure_hpa: float | None = None
    battery_v: float | None = None
    motion: bool | None = None
    gps_lat: float | None = None
    gps_lon: float | None = None
    gps_alt_m: float | None = None
    rssi: float | None = None
    snr: float | None = None


class SiteState(BaseModel):
    """Snapshot of current LoRaWAN sensors (no cameras)."""

    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sensors: list[SensorSummary] = Field(default_factory=list)
    sensor_count: int = 0
    active_motion: bool = False


class SiteStateAggregator:
    """Rolling-window collector for sensor readings.

    Call ingest_sensor_reading() from the MQTT subscriber callback. Call
    get_state() for a point-in-time snapshot, or sensor_summary() for one device.
    """

    def __init__(self, window_sec: int | None = None) -> None:
        self._lock = asyncio.Lock()
        self._window_sec = int(window_sec if window_sec is not None else settings.sensor_window_sec)
        # dev_eui -> deque of (timestamp, SensorReading)
        self._sensors: dict[str, deque[tuple[datetime, SensorReading]]] = {}

    async def ingest_sensor_reading(self, reading: SensorReading) -> SensorSummary:
        async with self._lock:
            if reading.dev_eui not in self._sensors:
                self._sensors[reading.dev_eui] = deque()
            self._sensors[reading.dev_eui].append((reading.received_at, reading))
            self._evict_old_sensor(reading.dev_eui)
            queue = self._sensors[reading.dev_eui]
            if not queue:
                # A delayed uplink is still summarised for the publisher, but it
                # does not remain in the rolling window.
                return self._summarize_sensor(
                    reading.dev_eui, deque([(reading.received_at, reading)])
                )
            return self._summarize_sensor(reading.dev_eui, queue)

    def _evict_old_sensor(self, dev_eui: str) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self._window_sec)
        queue = self._sensors[dev_eui]
        while queue and queue[0][0] < cutoff:
            queue.popleft()

    async def sensor_summary(self, dev_eui: str) -> SensorSummary | None:
        async with self._lock:
            queue = self._sensors.get(dev_eui)
            if not queue:
                return None
            return self._summarize_sensor(dev_eui, queue)

    async def get_state(self) -> SiteState:
        async with self._lock:
            sensors = [
                self._summarize_sensor(dev_eui, queue)
                for dev_eui, queue in self._sensors.items()
                if queue
            ]

        active_motion = any(s.motion for s in sensors if s.motion)
        return SiteState(
            sensors=sensors,
            sensor_count=len(sensors),
            active_motion=active_motion,
        )

    @staticmethod
    def _summarize_sensor(
        dev_eui: str, queue: "deque[tuple[datetime, SensorReading]]"
    ) -> SensorSummary:
        latest_ts, latest = queue[-1]
        return SensorSummary(
            dev_eui=dev_eui,
            last_seen=latest_ts,
            reading_count=len(queue),
            temperature_c=latest.temperature_c,
            humidity_pct=latest.humidity_pct,
            co2_ppm=latest.co2_ppm,
            pressure_hpa=latest.pressure_hpa,
            battery_v=latest.battery_v,
            motion=latest.motion,
            gps_lat=latest.gps_lat,
            gps_lon=latest.gps_lon,
            gps_alt_m=latest.gps_alt_m,
            rssi=latest.rssi,
            snr=latest.snr,
        )
