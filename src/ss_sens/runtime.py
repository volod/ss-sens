"""MQTT loop: ChirpStack uplinks -> rolling sensor state -> contract publishes."""

import asyncio
from typing import Any

from ss_kit.logging import get_logger
from ss_kit.mqtt import TopicBuilder

from .config import settings
from .mesh.site_state import SiteStateAggregator
from .sensors.contracts import ContractPublisher
from .sensors.lorawan_decoder import SensorReading
from .sensors.mqtt_subscriber import MqttSubscriber

logger = get_logger(__name__)


def _require_aiomqtt() -> Any:
    try:
        import aiomqtt
    except ImportError as exc:
        raise ImportError(
            "aiomqtt is required for ss-sens serve. Install it with: pip install ss-sens"
        ) from exc
    return aiomqtt


async def run_mesh(
    aggregator: SiteStateAggregator,
    *,
    reconnect_interval: float = 5.0,
    client_factory: Any | None = None,
) -> None:
    """Connect to the broker, ingest uplinks, and publish contract events.

    ``client_factory`` is an optional callable returning an async context manager
    whose value is an MQTT client (used by tests with a fake broker).
    """
    mqtt = settings.mqtt
    topics = TopicBuilder()
    subscriber = MqttSubscriber(mqtt=mqtt)

    if client_factory is None:
        aiomqtt = _require_aiomqtt()

        def client_factory() -> Any:
            return aiomqtt.Client(**mqtt.client_kwargs())

    while True:
        try:
            async with client_factory() as client:
                publisher = ContractPublisher(client, topics, settings.site_id)
                logger.info("MQTT connected to %s", mqtt.describe())

                async def on_sensor(reading: SensorReading) -> None:
                    summary = await aggregator.ingest_sensor_reading(reading)
                    await publisher.publish_from_reading(reading, summary)

                subscriber.on_sensor = on_sensor
                await subscriber.consume(client)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "MQTT connection lost (%s), reconnecting in %ss", exc, reconnect_interval
            )
            await asyncio.sleep(reconnect_interval)
