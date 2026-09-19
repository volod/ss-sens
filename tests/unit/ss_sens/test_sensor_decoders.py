from datetime import UTC

from ss_sens.sensors.lorawan_decoder import decode_chirpstack_uplink


def test_decode_chirpstack_uplink_normalizes_types_and_timestamp() -> None:
    reading = decode_chirpstack_uplink(
        {
            "deviceInfo": {"devEui": "aabbccddeeff0011", "applicationId": "site-a"},
            "time": "2026-05-01T12:34:56",
            "fCnt": "42",
            "rxInfo": [{"rssi": "-71", "snr": "8.5"}],
            "object": {
                "temperature": "21.5",
                "humidity": "65",
                "motion": "false",
                "lat": "50.45",
                "lon": "30.52",
            },
        }
    )

    assert reading is not None
    assert reading.received_at.tzinfo is UTC
    assert reading.f_cnt == 42
    assert reading.rssi == -71.0
    assert reading.snr == 8.5
    assert reading.temperature_c == 21.5
    assert reading.humidity_pct == 65.0
    assert reading.motion is False
    assert reading.gps_lat == 50.45
    assert reading.gps_lon == 30.52


def test_decode_chirpstack_uplink_ignores_unparseable_values() -> None:
    reading = decode_chirpstack_uplink(
        {
            "devEui": "bad-values",
            "fCnt": "not-an-int",
            "rxInfo": [{"rssi": "bad", "snr": None}],
            "object": {"temperature": "bad", "motion": "unknown"},
        }
    )

    assert reading is not None
    assert reading.f_cnt == 0
    assert reading.rssi is None
    assert reading.snr is None
    assert reading.temperature_c is None
    assert reading.motion is None
