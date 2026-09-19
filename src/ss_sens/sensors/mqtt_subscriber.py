"""Async MQTT subscriber for ChirpStack LoRaWAN uplinks.

Usage:
    subscriber = MqttSubscriber(on_sensor=handle_reading)
    await subscriber.run()   # blocks until cancelled

Requires the `aiomqtt` package (listed in the ss-sens extra).
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from ss_kit.logging import get_logger
from ss_kit.mqtt import MqttSettings

from ..config import settings
from .lorawan_decoder import SensorReading, decode_chirpstack_uplink

logger = get_logger(__name__)

OnSensorCallback = Callable[[SensorReading], Awaitable[None]]


class MqttSubscriber:
    """Subscribe to ChirpStack uplink topics and dispatch typed sensor readings.

    Attributes:
        on_sensor: Async callback invoked for each decoded LoRaWAN uplink.
    """

    def __init__(
        self,
        on_sensor: OnSensorCallback | None = None,
        mqtt: MqttSettings | None = None,
        chirpstack_topic: str | None = None,
    ) -> None:
        self.on_sensor = on_sensor
        self._mqtt = mqtt if mqtt is not None else settings.mqtt
        self._chirpstack_topic = chirpstack_topic or settings.chirpstack_topic

    async def run(self, reconnect_interval: float = 5.0) -> None:
        """Connect to the MQTT broker and process messages indefinitely.

        Reconnects automatically on connection loss.
        """
        try:
            import aiomqtt  # noqa: F401 — verified at runtime
        except ImportError as exc:
            raise ImportError(
                "aiomqtt is required for MqttSubscriber. "
                "Install it with: pip install 'selfsuvis[ss-sens]'"
            ) from exc

        import aiomqtt

        while True:
            try:
                async with aiomqtt.Client(**self._mqtt.client_kwargs()) as client:
                    logger.info("MQTT connected to %s", self._mqtt.describe())
                    await self.consume(client)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "MQTT connection lost (%s), reconnecting in %ss", exc, reconnect_interval
                )
                await asyncio.sleep(reconnect_interval)

    async def consume(self, client: Any) -> None:
        """Subscribe and dispatch on an already-connected MQTT client."""
        await client.subscribe(self._chirpstack_topic)
        logger.info("Subscribed to ChirpStack (%s)", self._chirpstack_topic)
        async for message in client.messages:
            await self.handle_message(str(message.topic), message.payload)

    async def handle_message(self, topic: str, payload: bytes) -> None:
        """Route an incoming message to the LoRaWAN handler when it is an uplink."""
        if "/event/up" in topic:
            await self._handle_lorawan(payload)

    async def _handle_lorawan(self, payload: bytes) -> None:
        reading = decode_chirpstack_uplink(payload)
        if reading and self.on_sensor:
            try:
                await self.on_sensor(reading)
            except Exception:
                logger.exception("Error in on_sensor callback")
