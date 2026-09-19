# ss-sens

Edge IoT sensor mesh: MQTT subscriber, LoRaWAN decoding, rolling sensor state, GPS-proximity
mesh fusion, analytics CLI, and a small FastAPI service that publishes contract sensor events.

This repository is staged from the video monorepo until `publish-ss-sens`. It pins
[`volod/ss-common`](https://github.com/volod/ss-common) tag `v0.1.0`. Camera ingest, combined
site snapshot, and threat aggregation stay in the video / fusion services; they consume
ss-sens over MQTT.

## Quick start

```bash
make ci                 # lint, spec-plan, unit tests
make ss-sens-up-min     # Mosquitto + ChirpStack + ss-sens serve
curl http://127.0.0.1:8081/health
```

`COOP_*` environment variables and MQTT topic strings are unchanged.

Operator guides: [docs/ss-sens/getting-started.md](docs/ss-sens/getting-started.md).
Current behavior: [docs/impl/current.md](docs/impl/current.md).
