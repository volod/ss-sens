"""Contract conversion and MQTT publish of LoRaWAN readings."""

import json
from datetime import datetime, timezone

from tests.support.fake_mqtt import FakeMqttClient

from ss_sens.mesh.site_state import SensorSummary
from ss_sens.sensors.contracts import (
    ContractPublisher,
    sector_from_gps,
    sensor_reading_to_event,
)
from ss_sens.sensors.lorawan_decoder import decode_chirpstack_uplink

INGEST = datetime(2026, 9, 19, 8, 0, 1, 250000, tzinfo=timezone.utc)


def _reading():
    reading = decode_chirpstack_uplink(
        {
            "time": "2026-09-19T07:59:58.412345Z",
            "deviceInfo": {
                "devEui": "70b3d57ed0060001",
                "applicationId": "a1b2c3d4-0000-4000-8000-000000000001",
            },
            "fCnt": 4211,
            "object": {
                "temperature": 21.4,
                "humidity": 63.5,
                "co2": 812,
                "pir": 1,
                "latitude": 50.4501,
                "longitude": 30.5234,
            },
            "rxInfo": [{"rssi": -97, "snr": 7.25}],
        }
    )
    assert reading is not None
    return reading


def test_sector_from_gps_uses_0_001_deg_grid() -> None:
    assert sector_from_gps(50.4501, 30.5234) == "grid:50450:30523"
    assert sector_from_gps(None, 30.0) == "unknown"


def test_sensor_reading_to_event_maps_payload_and_ingest_time() -> None:
    event = sensor_reading_to_event(_reading(), ingest_time=INGEST)
    assert event.node_id == "70b3d57ed0060001"
    assert event.sensor_type == "lorawan"
    assert event.sector_id == "grid:50450:30523"
    assert event.payload["temperature_c"] == 21.4
    assert event.payload["motion"] is True
    assert event.ingest_time == INGEST


async def test_contract_publisher_emits_reading_state_and_event() -> None:
    client = FakeMqttClient()
    publisher = ContractPublisher(client, site_id="local")
    reading = _reading()
    summary = SensorSummary(
        dev_eui=reading.dev_eui,
        last_seen=reading.received_at,
        reading_count=1,
        temperature_c=reading.temperature_c,
        motion=reading.motion,
    )
    await publisher.publish_from_reading(reading, summary)
    topics = [row["topic"] for row in client.published]
    assert "ss/v1/site/local/sensor/70b3d57ed0060001/reading" in topics
    assert "ss/v1/site/local/sensor/70b3d57ed0060001/state" in topics
    assert "ss/v1/site/local/node/70b3d57ed0060001/sensor-event" in topics
    state = next(row for row in client.published if row["topic"].endswith("/state"))
    assert state["retain"] is True
    event_payload = json.loads(
        next(row for row in client.published if row["topic"].endswith("/sensor-event"))["payload"]
    )
    assert event_payload["event_kind"] == "sensor"
    assert event_payload["node_id"] == "70b3d57ed0060001"
