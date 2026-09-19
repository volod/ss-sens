"""ss-sens producing classes serialize to the ss-common golden fixtures."""

import base64
import dataclasses
import json
import os
import pathlib
from collections import deque
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

import pytest
from pydantic import BaseModel

from ss_contracts.models import CONTRACTS
from ss_sens.mesh.site_state import SensorSummary, SiteStateAggregator
from ss_sens.sensors.contracts import sensor_reading_to_event
from ss_sens.sensors.lorawan_decoder import SensorReading, decode_chirpstack_uplink

REPO = pathlib.Path(__file__).resolve().parents[2]
GOLDEN = REPO / "tests" / "assets" / "contracts" / "golden"
UPDATE = os.environ.get("SS_UPDATE_GOLDEN") == "1"

INGEST_TIME = "2026-09-19T08:00:01.250000+00:00"

CHIRPSTACK_FULL: dict[str, Any] = {
    "deduplicationId": "3ac7e3c4-4401-4b8d-9386-a5c902f9202d",
    "time": "2026-09-19T07:59:58.412345Z",
    "deviceInfo": {
        "tenantId": "52f14cd4-c6f1-4fbd-8f87-4025e1d49242",
        "applicationId": "a1b2c3d4-0000-4000-8000-000000000001",
        "deviceName": "coop-north",
        "devEui": "70b3d57ed0060001",
    },
    "devAddr": "01fd2c3a",
    "fCnt": 4211,
    "fPort": 2,
    "data": "AQIDBAUGBwg=",
    "object": {
        "temperature": 21.4,
        "humidity": 63.5,
        "co2": 812,
        "pressure": 1008.2,
        "vbat": 3.61,
        "pir": 1,
        "latitude": 50.4501,
        "longitude": 30.5234,
        "altitude": 179.0,
    },
    "rxInfo": [{"gatewayId": "0016c001ff10a235", "rssi": -97, "snr": 7.25}],
}

CHIRPSTACK_MINIMAL: dict[str, Any] = {
    "time": "2026-09-19T08:01:00+00:00",
    "deviceInfo": {"devEui": "70b3d57ed0060002"},
    "fCnt": 0,
}


def _reading(payload: dict[str, Any]) -> SensorReading:
    reading = decode_chirpstack_uplink(payload)
    assert reading is not None
    return reading


def _sensor_state(payloads: list[dict[str, Any]]) -> SensorSummary:
    readings = [_reading(payload) for payload in payloads]
    window = deque((reading.received_at, reading) for reading in readings)
    return SiteStateAggregator._summarize_sensor(readings[-1].dev_eui, window)


CASES: dict[tuple[str, str], Callable[[], Any]] = {
    ("sensor-reading", "full"): lambda: _reading(CHIRPSTACK_FULL),
    ("sensor-reading", "minimal"): lambda: _reading(CHIRPSTACK_MINIMAL),
    ("sensor-state", "latest-of-window"): lambda: _sensor_state(
        [
            CHIRPSTACK_MINIMAL
            | {"deviceInfo": CHIRPSTACK_FULL["deviceInfo"], "time": "2026-09-19T07:44:58Z"},
            CHIRPSTACK_FULL,
        ]
    ),
    ("sensor-state", "radio-only"): lambda: _sensor_state([CHIRPSTACK_MINIMAL]),
    ("sensor-event", "lorawan"): lambda: sensor_reading_to_event(
        _reading(CHIRPSTACK_FULL),
        ingest_time=datetime.fromisoformat(INGEST_TIME),
    ),
}


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def to_wire(obj: Any) -> dict[str, Any]:
    if isinstance(obj, BaseModel):
        data = obj.model_dump(mode="json")
    elif hasattr(obj, "to_dict"):
        data = obj.to_dict()
    elif dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        data = dataclasses.asdict(obj)
    else:
        data = dict(obj)
    wire: dict[str, Any] = json.loads(json.dumps(data, default=_json_default))
    return {key: value for key, value in wire.items() if value is not None}


def assert_matches(actual: Any, expected: Any) -> None:
    if isinstance(expected, dict):
        assert isinstance(actual, dict) and actual.keys() == expected.keys(), (actual, expected)
        for key, value in expected.items():
            assert_matches(actual[key], value)
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), (actual, expected)
        for item, value in zip(actual, expected, strict=True):
            assert_matches(item, value)
    elif isinstance(expected, float) and not isinstance(actual, bool):
        assert actual == pytest.approx(expected, rel=1e-12, abs=1e-12)
    else:
        assert type(actual) is type(expected) and actual == expected, (actual, expected)


def _canonical(contract_id: str, wire: dict[str, Any]) -> dict[str, Any]:
    model = CONTRACTS[contract_id]
    emitted = set(wire) - set(model.model_fields)
    assert not emitted, f"{contract_id}: fields outside the contract: {sorted(emitted)}"
    return model.model_validate(wire).model_dump(mode="json", exclude_unset=True)


def _ids(cases: list[tuple[str, str]]) -> list[str]:
    return [f"{contract_id}/{name}" for contract_id, name in cases]


@pytest.mark.parametrize(("contract_id", "name"), sorted(CASES), ids=_ids(sorted(CASES)))
def test_current_class_serializes_to_golden(contract_id: str, name: str) -> None:
    wire = to_wire(CASES[contract_id, name]())
    canonical = _canonical(contract_id, wire)
    path = GOLDEN / contract_id / f"{name}.json"
    if UPDATE:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(canonical, indent=2) + "\n", encoding="utf-8")
    assert_matches(canonical, json.loads(path.read_text(encoding="utf-8")))
