"""MqttSubscriber dispatches ChirpStack uplinks without a live broker."""

from tests.support.fake_mqtt import FakeMqttClient, FakeMqttMessage

from ss_sens.sensors.lorawan_decoder import SensorReading
from ss_sens.sensors.mqtt_subscriber import MqttSubscriber

UPLINK = (
    b'{"deviceInfo":{"devEui":"aabbccddeeff0011"},'
    b'"time":"2026-09-19T08:00:00Z","fCnt":1,'
    b'"object":{"temperature":19.5}}'
)


async def test_handle_message_ignores_non_uplink_topics() -> None:
    seen: list[SensorReading] = []

    async def on_sensor(reading: SensorReading) -> None:
        seen.append(reading)

    subscriber = MqttSubscriber(on_sensor=on_sensor)
    await subscriber.handle_message("application/x/device/y/event/ack", UPLINK)
    assert seen == []


async def test_consume_decodes_uplink_and_invokes_callback() -> None:
    seen: list[SensorReading] = []

    async def on_sensor(reading: SensorReading) -> None:
        seen.append(reading)

    subscriber = MqttSubscriber(on_sensor=on_sensor)
    client = FakeMqttClient(
        incoming=[
            FakeMqttMessage("application/app/device/aabbccddeeff0011/event/up", UPLINK),
        ]
    )
    await subscriber.consume(client)
    assert client.subscriptions == [subscriber._chirpstack_topic]
    assert len(seen) == 1
    assert seen[0].dev_eui == "aabbccddeeff0011"
    assert seen[0].temperature_c == 19.5
