"""ss-sens FastAPI /site/sensors and /site/mesh with MQTT disabled."""

import asyncio
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from ss_sens.app import create_app
from ss_sens.mesh.fusion import SensorMeshFusion
from ss_sens.mesh.site_state import SiteStateAggregator
from ss_sens.sensors.lorawan_decoder import decode_chirpstack_uplink


def _reading():
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    reading = decode_chirpstack_uplink(
        {
            "deviceInfo": {"devEui": "70b3d57ed0060001"},
            "time": now,
            "object": {"temperature": 21.4, "pir": 1, "lat": 50.4501, "lon": 30.5234},
        }
    )
    assert reading is not None
    return reading


def test_health_and_empty_sensors() -> None:
    app = create_app(start_mqtt=False)
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}
        sensors = client.get("/site/sensors")
        assert sensors.status_code == 200
        body = sensors.json()
        assert body["sensor_count"] == 0
        assert body["sensors"] == []


def test_site_sensors_and_mesh_after_ingest() -> None:
    aggregator = SiteStateAggregator()
    fusion = SensorMeshFusion(aggregator)
    app = create_app(aggregator=aggregator, fusion=fusion, start_mqtt=False)
    asyncio.run(aggregator.ingest_sensor_reading(_reading()))
    with TestClient(app) as client:
        sensors = client.get("/site/sensors")
        assert sensors.status_code == 200
        body = sensors.json()
        assert body["sensor_count"] == 1
        assert body["sensors"][0]["dev_eui"] == "70b3d57ed0060001"
        assert body["active_motion"] is True
        mesh = client.get("/site/mesh")
        assert mesh.status_code == 200
        nodes = mesh.json()["nodes"]
        assert nodes[0]["node_id"] == "sensor:70b3d57ed0060001"
        assert nodes[0]["node_type"] == "sensor"


def test_delayed_uplink_is_summarised_but_not_kept() -> None:
    aggregator = SiteStateAggregator(window_sec=60)
    reading = _reading()
    reading.received_at = datetime.now(UTC) - timedelta(hours=2)
    summary = asyncio.run(aggregator.ingest_sensor_reading(reading))
    assert summary.dev_eui == reading.dev_eui
    state = asyncio.run(aggregator.get_state())
    assert state.sensor_count == 0
