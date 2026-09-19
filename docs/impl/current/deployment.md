# Deployment (arm64 slim)

ss-sens installs on a Raspberry Pi class host without ML dependencies. The
runtime image is CPU-only even when built on a CUDA host: `python:3.11-slim-bookworm`,
no NVIDIA base, no GPU device request, no analytics extra.

## Footprint gate

`make footprint` (`python -m ss_sens.quality.footprint`) resolves the base install
(no extras) with `uv pip compile --python-platform` for
`aarch64-unknown-linux-gnu` and `x86_64-unknown-linux-gnu` at Python 3.11. It
fails when torch, transformers, onnxruntime, onnxruntime-gpu, ctranslate2, or
streamlit appear, direct or transitive. Pins land under `$DATA_DIR/footprint/`.
A planted torch dependency fails the gate (`tests/unit/ss_sens/test_footprint.py`).

Resolved base install (both platforms, 28 named pins plus ss-common git tag
`v0.1.0`): aiomqtt, annotated-doc, annotated-types, anyio, certifi, cffi, click,
cryptography, fastapi, h11, httpcore, httptools, httpx, idna, paho-mqtt,
pycparser, pydantic, pydantic-core, pyjwt, python-dotenv, pyyaml, starlette,
typing-extensions, typing-inspection, uvicorn, uvloop, watchfiles, websockets.

`make ci` includes this gate.

## Multi-arch image

`docker/ss-sens/Dockerfile.ss-sens` is a two-stage uv install from `uv.lock`
into `/opt/ss-sens`. Commands:

```bash
make image                          # linux/arm64,linux/amd64, load, sizes, QEMU smoke
./scripts/ss-sens/ss-sens-image.sh build
./scripts/ss-sens/ss-sens-image.sh load amd64   # or arm64
```

`docker buildx build --platform linux/arm64,linux/amd64` writes an OCI archive
to `$DATA_DIR/ss-sens/images/ss-sens-linux-arm64-amd64.oci.tar`. Loaded tags
are `ss-sens:local-amd64` and `ss-sens:local-arm64`; the native tag is also
`ss-sens:local`. Compose uses `image: ${SS_SENS_IMAGE:-ss-sens:local}`.

On this CUDA amd64 host the arm64 image starts under QEMU
(`docker run --platform linux/arm64`) and answers `GET /site/sensors` (empty
rolling window when MQTT is absent). Recorded sizes (`docker image inspect
.Size`, all layers, 2026-09-19T18:42:23Z):

| Tag | Platform | Size |
| --- | --- | --- |
| `ss-sens:local-amd64` | linux/amd64 | 277188070 bytes (264.3 MiB) |
| `ss-sens:local-arm64` | linux/arm64 | 302378726 bytes (288.4 MiB) |
| OCI archive | linux/arm64,linux/amd64 | 131472896 bytes (125.4 MiB) |

Evidence file: `$DATA_DIR/ss-sens/images/sizes.txt`. The venv layer added on
top of `python:3.11-slim-bookworm` is about 63 MiB on both platforms.

## Edge compose profile

Profile `edge` is the Pi stack: Mosquitto and ss-sens (always on), ChirpStack
with gateway bridge, REST API, Postgres, Redis, and node-exporter. Every
service has CPU and memory limits.

```bash
make ss-sens-up-edge    # COMPOSE_PROFILES=edge
```

Stated resource budget (Raspberry Pi class, 4 GB RAM / 4 cores): compose
ceilings sum to **1.75 CPU and 1664 MiB**. OS, Docker, and page cache use the
rest of 4 GB. A 24-hour soak on real hardware is
[`sens-pi-soak`](../plan.md#sens-pi-soak); that run uses a published image after
the staging repository exports this tree.

| Service | CPU ceiling | Memory ceiling |
| --- | --- | --- |
| mosquitto | 0.15 | 128M |
| ss-sens | 0.25 | 256M |
| chirpstack-postgres | 0.50 | 512M |
| chirpstack-redis | 0.10 | 96M |
| chirpstack | 0.50 | 512M |
| chirpstack-gateway-bridge | 0.10 | 64M |
| chirpstack-rest-api | 0.10 | 64M |
| node-exporter | 0.05 | 32M |

The `lorawan` profile stays for the min/nettop bundle (no node-exporter).
The `metrics` profile (Prometheus, Grafana, cAdvisor) stays until
`stage-ss-control` moves it; node-exporter is on both `edge` and `metrics`.

Env templates set `COOP_SS_SENS_CPUS` / `COOP_SS_SENS_MEMORY`. Offline bundles
accept `--bundle edge` (`ss-sens-release.sh`, `ss-sens-install.sh`).
