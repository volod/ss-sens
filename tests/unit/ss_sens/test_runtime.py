"""run_mesh publishes contract messages from a fake MQTT client."""

import asyncio
import json
from datetime import datetime, timezone

from tests.support.fake_mqtt import FakeMqttClient, FakeMqttMessage

from ss_sens.mesh.site_state import SiteStateAggregator
from ss_sens.runtime import run_mesh


def _uplink() -> bytes:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        b'{"deviceInfo":{"devEui":"70b3d57ed0060001"},'
        + f'"time":"{now}","fCnt":3,'.encode()
        + b'"object":{"temperature":18.0,"pir":0}}'
    )


async def test_run_mesh_ingests_uplink_and_publishes_contracts() -> None:
    client = FakeMqttClient(
        incoming=[
            FakeMqttMessage("application/app/device/70b3d57ed0060001/event/up", _uplink()),
        ],
        hang=True,
    )
    aggregator = SiteStateAggregator()
    task = asyncio.create_task(run_mesh(aggregator, client_factory=lambda: client))
    try:
        for _ in range(50):
            if any(row["topic"].endswith("/sensor-event") for row in client.published):
                break
            await asyncio.sleep(0.02)
        state = await aggregator.get_state()
        assert state.sensor_count == 1
        topics = [row["topic"] for row in client.published]
        assert any(t.endswith("/reading") for t in topics)
        assert any(t.endswith("/state") for t in topics)
        event = json.loads(
            next(
                row["payload"] for row in client.published if row["topic"].endswith("/sensor-event")
            )
        )
        assert event["node_id"] == "70b3d57ed0060001"
        assert event["payload"]["temperature_c"] == 18.0
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
