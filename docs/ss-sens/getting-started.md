# Getting Started

This guide starts the ss-sens IoT mesh (Mosquitto, ChirpStack, and `ss-sens serve`).
Camera ingest, combined site snapshot, and threat aggregation stay in ss-video;
they consume this service over MQTT.

## Prerequisites

- Docker Engine 24.0+ with Compose V2
- Linux amd64 or arm64
- Python 3.11+ (Raspberry Pi OS Bookworm ships 3.11)
- At least 4 GB RAM and 4 CPU cores for the `edge` profile (Pi class).
  8 GB / 4 cores for the LoRaWAN profile plus video on a nettop.

## Installation

### 1. Enter this repository

While staged, this tree is `projects/ss-sens/` in the video monorepo. After
publish it is its own clone:

```bash
cd projects/ss-sens   # staged
# or: git clone <ss-sens-url> && cd ss-sens
make bootstrap        # uv sync --locked --all-extras
```

### 2. Configure environment (first run)

**Option A: Generate from template** (recommended):

```bash
# Production (default)
./scripts/ss-sens/ss-sens-env.sh

# Development
./scripts/ss-sens/ss-sens-env.sh dev

# Test / CI -- localhost bindings, isolated data dir, reduced limits
./scripts/ss-sens/ss-sens-env.sh test
```

This creates `.data/.env` with randomly generated secrets. Save the printed
credentials securely.

**Option B: Manual setup**:

```bash
cp src/ss_sens/env/prod.env .data/.env
# Edit .data/.env and replace any remaining REPLACE_ME values
```

To list credentials later:

```bash
./scripts/ss-sens/ss-sens-credentials.sh --list
```

Key variables:

| Variable | Description |
|----------|-------------|
| `DATA_DIR` | Bind-mount root (default: `.data/`). Mosquitto certs live under `$DATA_DIR/coop/`. |
| `OR_HOSTNAME` | Hostname baked into Mosquitto TLS certs (default: `localhost`) |
| `MOSQUITTO_HEALTH_PASSWORD` | MQTT health-check password |
| `CHIRPSTACK_PG_PASSWORD` | ChirpStack database password |
| `CHIRPSTACK_API_SECRET` | ChirpStack API secret (base64) |
| `CHIRPSTACK_MQTT_PASSWORD` | ChirpStack MQTT password |
| `FRIGATE_MQTT_PASSWORD` | ACL user for the video Frigate publisher (Frigate itself is not in this stack) |

`COOP_*` names and MQTT topic strings are unchanged.

### 3. Cameras (optional, video repository)

Frigate and camera CLIs live in ss-video (`make frigate-up`,
`scripts/ssv/ssv-camera.sh`). Both compose files join Docker network
`selfsuvis-net` so the video API can reach Mosquitto.

### 4. Start the stack

Bootstrap creates `.data/.env`, data directories, TLS certificates, and MQTT
users when missing:

```bash
make ss-sens-up-min
# equivalent: COMPOSE_PROFILES=lorawan ./scripts/ss-sens/ss-sens-bootstrap.sh up -d

# Raspberry Pi class host (LoRaWAN + node-exporter, 4 GB budget):
make ss-sens-up-edge
# equivalent: COMPOSE_PROFILES=edge ./scripts/ss-sens/ss-sens-bootstrap.sh up -d
```

PUID/PGID are set from the current user. For compose-only commands (logs,
down): `./scripts/ss-sens/ss-sens-compose.sh logs -f`.

Monitor startup:

```bash
make ss-sens-logs
# or: ./scripts/ss-sens/ss-sens-compose.sh logs -f --tail=100
```

### 5. Verify services

```bash
make ss-sens-status
curl http://127.0.0.1:8081/health
```

Expected containers on the min / lorawan profile: `ss-sens`, `ss-sens-mosquitto`,
`ss-sens-chirpstack`, `ss-sens-cs-gwbridge`, `ss-sens-cs-rest`,
`ss-sens-cs-postgres`, `ss-sens-cs-redis`. The `edge` profile adds
`ss-sens-node-exporter`.

## Accessing services

| Service | URL | Notes |
|---------|-----|-------|
| ss-sens | http://localhost:8081 | `/health`, `/site/sensors`, `/site/mesh` |
| ChirpStack | http://localhost:8080 | LoRaWAN server |
| ChirpStack REST | http://localhost:8090 | REST API |
| Prometheus | http://localhost:9090 | `make ss-sens-metrics-up` |

## Integrating with the video API

While staged, start both stacks from the video repository root:

```bash
make up
make frigate-up
make -C projects/ss-sens ss-sens-up-min
```

Video `.env` MQTT settings should match this broker (`COOP_MQTT_HOST=mosquitto`
on `selfsuvis-net`). Combined `/site/state`, `/site/cameras`, `/site/threat`,
and `/site/synthesis` stay on the video API.

Local process without Docker:

```bash
make bootstrap
python -m ss_sens serve
```

Analytics (`ss-sens-analytics`) needs the `analytics` extra.

---

## Next Steps

- [Integration Guide](integration.md) -- MQTT topics and contract events
- [Sensor Integration](sensor-integration.md) -- adding LoRaWAN devices
- [Configuration Guide](configuration.md) -- env vars and tuning
- [Analytics Guide](analytics.md) -- log analytics CLI (`ss-sens-analytics`)
- [Testing Guide](testing.md) -- `make ci` and stack tests
- [Troubleshooting](troubleshooting.md) -- common issues
