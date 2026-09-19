# Current Implementation

ss-sens is the Python package `ss_sens` plus a containerized edge stack
(`docker/ss-sens/docker-compose.ss-sens.yml`, config under `config/ss-sens/`,
ops scripts under `scripts/ss-sens/`). It is its own FastAPI process: it owns
ChirpStack ingest, the sensor rolling window, GPS-proximity mesh fusion, and
contract `SensorEvent` publishes. The video API does not import `ss_sens`.

This tree is a complete repository root (Python >= 3.11, `uv.lock`, `[tool.ss-split]
siblings = []`, ss-common git tag `v0.1.0`). While staged under the video
monorepo, `make -C projects/ss-sens ci` and `make split-check P=ss-sens` are
the gates. Field-device forward work lives in [plan.md](plan.md).

| Need | Read |
| --- | --- |
| Modules, contracts, operations | this page |
| Arm64 slim image, footprint gate, Pi `edge` profile | [deployment.md](current/deployment.md) |

**Gate.** `make ci` bootstraps the locked environment with every extra, then Ruff,
doc-link and spec-plan checks, the footprint gate, and `tests/unit`. Stack tests
are `make test-stack` after `make ss-sens-up-min`. Multi-arch image + QEMU smoke
is `make image` (not in `make ci`).

Camera code lives on the video side. Combined camera + sensor snapshots, scene
synthesis, and the threat feed stay on the production server. Everything is
optional: the API starts when the MQTT broker is unreachable or `aiomqtt` is
absent (ADR 0009, 0010).

## Service split

| Process | Package | Owns | HTTP |
| --- | --- | --- | --- |
| `ss-sens serve` (`python -m ss_sens serve`) | `ss_sens` | `MqttSubscriber`, `SiteStateAggregator`, `SensorMeshFusion`, contract publishes | `GET /health`, `/site/sensors`, `/site/mesh` on `COOP_HTTP_PORT` (8081) |
| video API | `selfsuvis` | `ContractEventConsumer`, `CombinedSiteSnapshot`, `SensorEventIngestor`, `RealtimeThreatAggregator`, `SceneSynthesizer`, `CameraStreamService` | `GET /site/state`, `/site/cameras`, `/site/threat`, `/site/synthesis`, `WS /site/stream` |

This package does not import `selfsuvis` or `ssv_vdp`. Base extras are
`ss-common[mqtt,web]` plus `aiomqtt`, `pydantic`, `httpx`, and `uvicorn`. Analytics
(`pandas`, `jinja2`, `rich`, `docker`) sit behind `ss-sens[analytics]`. Console
scripts: `ss-sens`, `ss-sens-analytics`. `COOP_*` env vars and MQTT topic strings
are unchanged.

## ss-sens modules (verified surface)

| Module | Key classes | Role |
| --- | --- | --- |
| `ss_sens/config.py` | `SensSettings` | `COOP_MQTT_*`, `COOP_CHIRPSTACK_TOPIC`, `COOP_SITE_ID`, rolling window (300 s), HTTP bind |
| `sensors/mqtt_subscriber.py` | `MqttSubscriber` | ChirpStack uplinks only (`application/+/device/+/event/up`) |
| `sensors/lorawan_decoder.py` | `SensorReading`, `decode_chirpstack_uplink()` | Uplink JSON -> typed reading |
| `sensors/contracts.py` | `ContractPublisher`, `sensor_reading_to_event()` | Publish `SensorEvent` / `SensorState` on the ss-common topic map; GPS sector grid 0.001 deg (~110 m) |
| `mesh/site_state.py` | `SiteStateAggregator`, `SiteState` | Sensor rolling window; source of truth for `GET /site/sensors` |
| `mesh/fusion.py` | `SensorMeshFusion`, `SiteMesh` | GPS-proximity neighbour links; `GET /site/mesh` |
| `runtime.py` | `run_mesh()` | MQTT loop: uplink -> aggregator -> contract publish |
| `analytics/` | collector, parsers, reporter | `ss-sens-analytics` CLI |

An empty rolling window after timestamp eviction still returns a one-shot
summary for that ingest so delayed uplinks do not crash the subscriber.

## Video-side camera and combined snapshot

| Module | Key classes | Role |
| --- | --- | --- |
| `pipeline/realtime/camera_events.py` | `CameraEvent`, `FrigateEventConsumer` | Frigate detection events |
| `pipeline/realtime/rtsp_bridge.py` | `FrigateRtspBridge` | Frigate cameras -> MediaMTX `ssv/{camera}` |
| `pipeline/realtime/sound_analyzer.py` | `SoundAnalyzer`, `AcousticObservation` | Per-camera faster-whisper + FFT |
| `pipeline/realtime/camera_settings.py` | `CameraSettings` | `COOP_FRIGATE_*` plus shared `COOP_MQTT_*` for the API consumer |
| `pipeline/realtime/site_snapshot.py` | `CombinedSiteSnapshot` | Sensor rows from contract `sensor-state` / `sensor-event`; camera rows from local Frigate |
| `pipeline/realtime/scene_synthesis.py` | `SceneSynthesizer` | Combined snapshot + `scene_timeline` captions -> LLM narrative |
| `pipeline/realtime/contract_consumer.py` | `ContractEventConsumer` | `ss_kit[mqtt]` subscriber of contract topics; optional Frigate MQTT |
| `pipeline/realtime/sensor_ingest.py` | `SensorEventIngestor` | Contract sensor events and camera detections -> `RealtimeThreatAggregator` |
| `app/services/camera_streams.py` | `CameraStreamService` | Discover Frigate cameras, register MediaMTX, start captioner / sound analyzer |
| `selfsuvis/camera_cli.py` | -- | Backing for `scripts/ssv/ssv-camera.sh` |

`selfsuvis.config` no longer re-exports ss-sens settings.

## Edge stack containers

Profiles: `lorawan`, `edge`, `metrics` (Make targets `ss-sens-up`,
`ss-sens-up-min`, `ss-sens-up-edge`, `ss-sens-metrics-up`). Frigate stays in
the video repository (`make frigate-up`). Both compose files use the Docker
network `selfsuvis-net` so the video API can reach Mosquitto.

The Pi profile is `edge`: Mosquitto, ChirpStack with gateway bridge, Postgres,
Redis, ss-sens, and node-exporter, with per-service CPU and memory limits that
sum to 1.75 CPU / 1664 MiB (stated 4 GB / 4-core budget). Details:
[deployment.md](current/deployment.md).

| Component | Container | Role |
| --- | --- | --- |
| ss-sens | `ss-sens` | FastAPI sensor mesh service (CPU-only image `ss-sens:local`) |
| Mosquitto | `ss-sens-mosquitto` | Central MQTT bus; TLS on 8883; ACL user `ss-sens` |
| ChirpStack v4 | `ss-sens-chirpstack` (+ `ss-sens-cs-gwbridge`, `ss-sens-cs-rest`, `ss-sens-cs-postgres`, `ss-sens-cs-redis`) | LoRaWAN network server (EU868) |
| node-exporter | `ss-sens-node-exporter` | Host metrics on profiles `edge` and `metrics` |
| Frigate | `ssv-frigate` | NVR with detection; events -> `frigate/#` (video repository) |
| Prometheus / Grafana / cAdvisor | `ss-sens-prometheus`, `ss-sens-grafana`, `ss-sens-cadvisor` | Optional `metrics` profile (stays until ss-control) |

Bind-mount runtime data stays under `$DATA_DIR/coop/` (Mosquitto certs, Frigate
live config). Compose joins `selfsuvis-net` so the API can reach `mosquitto`.

Data flow:

```
LoRa device -> gateway -> UDP:1700 -> gw-bridge -> MQTT eu868/# -> ChirpStack
           -> MQTT application/{app}/device/{devEUI}/event/up
           -> ss-sens MqttSubscriber -> SiteStateAggregator + SensorMeshFusion
           -> contract SensorEvent on ss/v1/site/{site_id}/...
           -> video ContractEventConsumer -> CombinedSiteSnapshot
              + SensorEventIngestor -> RealtimeThreatAggregator
RTSP/USB camera -> Frigate -> MQTT frigate/# -> video ContractEventConsumer
```

## Message contracts

`SensorReading`, `CameraEvent`, `AcousticObservation`, the per-device
`SensorSummary` of `SiteState`, and the realtime `SensorEvent` and `ThreatEvent`
have ODCS contracts, golden fixtures, and `ss/v1/...` MQTT topics in published
ss-common
([contracts](https://github.com/volod/ss-common/blob/v0.1.0/docs/impl/current/contracts.md#site-event-contracts),
[topic map](https://github.com/volod/ss-common/blob/v0.1.0/docs/impl/current/contracts.md#topic-map)).
`tests/unit/test_site_event_contracts.py` asserts that these classes
serialize to the fixtures through their producing code paths.

## Operations

- `scripts/ss-sens/ss-sens-bootstrap.sh` -- data dirs, TLS certs, MQTT users, stack up.
- `ss-sens-ctl.sh`, `ss-sens-compose.sh` (injects PUID/PGID).
- `ss-sens-release.sh` -- offline air-gapped bundles: `standard`, `min` (no video),
  `video`, `--with-metrics`; Make wrappers `ss-sens-release*`.
- Camera add/list lives in the video repository (`scripts/ssv/ssv-camera.sh`).
- Integration against a live stack: `make ss-sens-up-min`, then the video
  repository's `tests/integration/test_ss_sens_decouple.py` (fixture uplink ->
  `/site/sensors` and API `/site/state` / `/site/threat`).
- Sizing (pilot): 3-5 sites, 5-10 LoRaWAN devices, 2-6 cameras on one amd64 nettop
  (8 GB / 4 cores budget in `docs/ss-sens/architecture.md`). Pi class hosts use
  `make ss-sens-up-edge` (4 GB / 4 cores stated budget in
  [deployment.md](current/deployment.md)).

Full docs: `docs/ss-sens/` (getting-started, architecture, sensor-integration,
integration, analytics, distribution, testing, troubleshooting).

## Deliberate gaps (drive the forward plan)

The mesh today is **uplink-only and consume-only**:

- No downlink/command path to devices (ChirpStack downlinks unused).
- No device provisioning automation (devices are registered by hand in the UI).
- No device inventory/registry, health ledger, or firmware version tracking.
- No first-party firmware: nodes are third-party devices with vendor codecs.
- No LoRa P2P/mesh (Meshtastic-style) transport, only LoRaWAN star topology.
- No HAB (high-altitude balloon) payload/tracking support.
- OpenRemote runs but is not synchronized with ChirpStack device state.
- No Node-RED (or similar) operator-editable automation layer.
- RF/SIGINT sensing is limited to what LoRaWAN devices report; no presence
  scanning, no spectrum awareness, no FPGA signal front-end.

These gaps are the subject of the field-device-layer scope in the
[forward plan](plan.md).
