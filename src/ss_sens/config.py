"""ss-sens runtime configuration -- reads from environment / .env."""

from ss_kit.env import env_int, env_str
from ss_kit.mqtt import MqttSettings


class SensSettings:
    """Settings for the ss-sens sensor mesh service.

    MQTT broker fields use the ``COOP_MQTT_`` prefix via ``ss_kit.mqtt.MqttSettings``.
    Frigate / camera settings live on the video side (``COOP_FRIGATE_*`` unchanged).
    """

    mqtt: MqttSettings = MqttSettings.from_env("COOP_MQTT_")
    chirpstack_topic: str = env_str("COOP_CHIRPSTACK_TOPIC", "application/+/device/+/event/up")
    sensor_window_sec: int = env_int("COOP_SENSOR_WINDOW_SEC", 300)
    site_id: str = env_str("COOP_SITE_ID", "local")
    http_host: str = env_str("COOP_HTTP_HOST", "0.0.0.0")
    http_port: int = env_int("COOP_HTTP_PORT", 8081)
    api_key: str = env_str("COOP_API_KEY", "")

    def validate(self) -> None:
        """Raise ValueError for hard configuration errors."""
        if self.sensor_window_sec < 10:
            raise ValueError("COOP_SENSOR_WINDOW_SEC must be >= 10 seconds")
        if not self.site_id or "/" in self.site_id or "+" in self.site_id or "#" in self.site_id:
            raise ValueError("COOP_SITE_ID must be a single MQTT topic level")
        problems = self.mqtt.tls.errors()
        if problems:
            raise ValueError("; ".join(problems))


settings = SensSettings()
