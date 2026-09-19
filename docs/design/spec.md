# ss-sens Specification

ss-sens is the edge IoT sensor mesh: MQTT subscriber, LoRaWAN decoding, rolling sensor state,
GPS-proximity mesh fusion, analytics CLI, and a FastAPI service (`/site/sensors`, `/site/mesh`,
later the device registry). It publishes contract sensor events on MQTT. Camera ingest, combined
site snapshot, scene synthesis, and threat aggregation stay in the video and fusion services;
they consume this service over MQTT.

This repository pins [`volod/ss-common`](https://github.com/volod/ss-common) tag `v0.1.0`
(`ss-common[mqtt,web]`). `COOP_*` env vars and MQTT topic strings stay.

## Sensor mesh

**Problem.** The IoT mesh cannot share a Python install with the video stack: that package pulls
torch, faster-whisper, transformers, and streamlit. The mesh must run on a Raspberry Pi class
host and publish contract events that video and fusion consume.

**Behavior.** Package `ss_sens` owns ChirpStack ingest, the sensor rolling window, mesh topology,
analytics, and `ss-sens serve`. Compose stack: Mosquitto, ChirpStack with gateway bridge,
Postgres, Redis, the ss-sens service, and a node exporter. Frigate and camera CLIs live in
ss-video.

**Boundary.** No web UI for people on the Pi. No import of `selfsuvis` or `ssv_vdp`.

**Evaluation.** Decoder unit tests, the arm64 footprint gate, and `make ci` are
green. A 24-hour soak of the `edge` profile on a real Pi records CPU, memory, and
restarts against a published image. Valid negative result: a decoder that cannot
express a vendor payload is listed and skipped; if the stack exceeds a 4 GB Pi
budget, the measured numbers set the minimum hardware (8 GB Pi 5 or nettop).

## Field device layer

The mesh is uplink-only and consume-only (see
[deliberate gaps](../impl/current.md#deliberate-gaps-drive-the-forward-plan)):
it ingests whatever third-party LoRaWAN devices emit, but it cannot provision, command, update,
or even inventory the devices it depends on, and it fields no first-party sensing hardware. This
layer adds that.

### Why this scope

- **Persistent site awareness is the product.** Buyers of outdoor-autonomy systems (critical
  infrastructure, energy sites, agriculture, perimeter security) pay for continuous ground truth
  between missions, not for one-off video analysis. Camera-only systems have blind spots at night,
  in fog, and outside frustums; the differentiator is a cheap multi-modal mesh (environmental, RF,
  acoustic, motion) that keeps the world model honest.
- **Off-grid resilience is a hard requirement.** The pattern proven in recent conflict and
  disaster response is infrastructure-less comms (LoRa mesh, Meshtastic-class networks),
  air-gapped deployable stacks (already shipped as `ss-sens-release` offline bundles), and
  stratospheric platforms (HAB) as low-cost persistent relay and wide-area observation.
- **Edge intelligence on constrained silicon is maturing fast.** ESP32-class MCUs run useful
  TinyML; STM32 covers multi-year battery deployments; the XC7Z020 (Zynq-7000) gives a
  deterministic FPGA front-end for RF spectral work. Sending semantics instead of raw samples cuts
  bandwidth, power, and RF signature.
- **Agent-operated infrastructure is the near-term ops trend.** That requires machine-readable
  device state (a registry), declarative provisioning (manifests, not UI clicks), and closed-loop
  verification (health ledger, acceptance gates). Every operation is exposed as CLI or API.
- **Open platforms win the integration battle.** ChirpStack, Frigate, Node-RED, and Meshtastic
  are the de-facto open stacks; the value is fusion, world model, and threat analytics on top.

### Stakeholder demand map

| Stakeholder | What they need from this scope |
| --- | --- |
| Operators | One pane of glass behind ss-control (composition or OpenRemote), editable automation without code (Node-RED), incident ack and dismiss from the v1 API |
| Planners | Coverage and mesh-health views, site survey from HAB tracks, RF baseline maps |
| Engineers | Reproducible firmware builds, one-command flash, OTA, device registry with firmware ledger, CI that gates every stack |
| Owners | Offline installable bundles, low cost per node (COTS boards), privacy and RF-compliance evidence |
| Users and robots | Better threat advisories: more independent modalities feeding the two-source evidence gate |

### Technology bets and simplicity rules

- **Python remains the integration plane.** Ingestion, APIs, and analytics stay in ss-sens. No
  new brokers, no Kubernetes.
- **One firmware build system.** C and C++ on the Arduino framework under PlatformIO for both
  ESP32 and STM32 targets: one `platformio.ini`, one native unit-test runner, one CI job.
- **Go for exactly one thing:** the field gateway agent (`sencoop-agent`), a single static
  cross-compiled binary so gateways need no Python runtime.
- **Rust is allowed but not scheduled.** Adopt it only when a concrete SDR, DSP, or edge-kernel
  path needs memory-safe performance, and record the decision in the owning specification section
  first.
- **FPGA work is isolated and sim-first.** The XC7Z020 builds in a pinned Vivado container, and
  every software consumer runs against a numpy simulation.
- **Cross-language contracts are golden-fixture tested.** The wire format between firmware (C),
  ChirpStack codec (JS), and ingestion (Python) is one committed set of golden frames.

### Target hardware

| Chip or board | Role | Toolchain |
| --- | --- | --- |
| ESP32-S3 (Heltec WiFi LoRa 32 V3, SX1262) | LoRaWAN sensor node, presence scanner, HAB tracker and gateway | PlatformIO, Arduino, RadioLib |
| STM32WL55 (Nucleo-WL55JC) | Multi-year battery sensor node | PlatformIO, Arduino (STM32duino, STM32LoRaWAN) |
| XC7Z020 (PYNQ-Z2) | Deterministic RF spectral front-end | Vivado 2022.1 (pinned container), PYNQ 3.x |
| Raspberry Pi class arm64 or amd64 nettop | ss-sens gateway stack and `sencoop-agent` | Docker, Go static binary |

### Device management

**Problem.** Devices cannot be inventoried, provisioned declaratively, or commanded, and gateways
need a field tool that does not require Python.

**Behavior.** Device registry with health and firmware ledgers; declarative ChirpStack
provisioning from a manifest; a rate-limited downlink command bus with an audit trail; the
`sencoop-agent` Go binary for discovery, flashing, inventory, and health.

**Boundary.** No FUOTA, no multicast, no UI-only operation.

**Evaluation.** Fixture tests for registry upsert, heartbeat, and ledger append; provisioning is
idempotent (a second apply is zero-change); downlink rate limit and encoding golden tests; the
agent aborts on sha256 mismatch before invoking a flash tool. Valid negative result: provisioning
the ChirpStack REST API cannot express stays manual and is documented as a gap.

### First-party firmware

**Problem.** Nodes are third-party devices with vendor codecs; there is no multi-year battery
node, no OTA path, and no presence sensing.

**Behavior.** One PlatformIO workspace for ESP32 and STM32; the ssvnode wire contract tested
identically in C, Python, and JS; ESP32 and STM32WL sensor nodes; WiFi OTA with sha256-verified
manifests; a counts-only presence scanner behind a privacy flag.

**Boundary.** No FUOTA, no secure boot, no identifier leaves a presence scanner, and default-on
presence ingest is gated by a privacy review.

**Evaluation.** Golden frames decode byte-identically in C, Python, and JS; every PlatformIO env
builds; a test proves the presence block can encode only counts and RSSI. Valid negative result: a
board that misses its power budget keeps its build and records measured current.

### Cross-stack CI

**Problem.** Python, firmware, Go, and FPGA work have no common gate.

**Behavior.** Path-filtered CI jobs per toolchain, one local `make ci` that reproduces them, and
offline bundles that embed firmware and agent artifacts.

**Boundary.** No hardware-in-the-loop runners and no bitstream builds in CI.

**Evaluation.** `make ci` is green on a full checkout and on a toolchain-less checkout (skips with
one warning per missing toolchain); a bundle contains its declared artifacts. Valid negative
result: a toolchain too costly for hosted CI stays local-only and is listed.

### Mesh transports

**Problem.** LoRaWAN star topology is the only transport; coverage ends at gateway range.

**Behavior.** Stock Meshtastic nodes, through an MQTT-uplink gateway node, appear as registry
devices and mesh members; positions and telemetry land in site state; text messages land in the
device ledger.

**Boundary.** No custom Meshtastic firmware; the mesh is not a router.

**Evaluation.** Every handled port number has a fixture-decode test; unknown ports are counted and
skipped. Valid negative result: a port whose protobuf cannot be decoded with the pinned package is
listed and skipped.

### Field pilot

**Problem.** No real site has run the mesh long enough to back the documentation with measured
numbers.

**Behavior.** One reference deployment (3 sensor nodes, 2 Meshtastic nodes, 1 LoRaWAN gateway,
1 camera, 1 nettop) with a seven-day soak report.

**Boundary.** One site; no hardware-in-the-loop CI.

**Evaluation.** A soak report with uptime, packet loss, battery slope, and at least one fused
camera and sensor incident. Valid negative result: every deviation from the documented sizing
becomes a forward task.

### Operator automation

**Problem.** Operators cannot change automation without code or see devices in one place.

**Behavior.** Node-RED in ss-control with seeded flows (uplink normalization into the v1 events
API, a camera-to-downlink example, a stack-health dashboard); OpenRemote asset sync only if
ss-control evaluation keeps OpenRemote; a week of operator use with structured feedback.

**Boundary.** No custom Node-RED nodes; Node-RED is admin-only behind the identity provider.

**Evaluation.** A fixture publish reaches the v1 events API through the seeded flow; flows load
without missing nodes; the operator feedback summary is committed. Valid negative result: operator
needs the pane cannot meet become forward tasks with the feedback attached.

### HAB collection

**Problem.** Coverage is limited to one site; a high-altitude balloon can relay and observe a
region for the cost of a hobby launch.

**Behavior.** HAB payload and ground station stream telemetry into the mesh with a flight state
machine. After recovery, the video and fusion repositories turn the flight video plus track into
a mission with a coverage footprint.

**Boundary.** No cutdown control, landing prediction, or amateur-radio modes. The post-flight
mission run is ss-fusion work.

**Evaluation.** Simulated ascent replay produces a monotonic track, correct burst detection, and a
complete track log. Valid negative result: a real flight that misses the simulated behavior
records the deviation as forward work.

### RF sensing

**Problem.** RF awareness is limited to what LoRaWAN devices report; there is no spectrum view and
no RF baseline.

**Behavior.** An XC7Z020 spectral front-end (simulation first) publishes RF spectra into the mesh;
per-node RF baselines and anomaly scores, with an optional Gaussian-process field map, feed
contract events to fusion-rt.

**Boundary.** No emitter localization, signal classification, or active transmission.

**Evaluation.** A known synthetic tone is found within one bin; an injected anomaly is flagged and
a quiet series is not. Valid negative result: hardware results outside simulation tolerance keep
the simulation path and record the delta.

## Related repositories

This repository is [`volod/ss-sens`](https://github.com/volod/ss-sens). Video and fusion
consume contract events over MQTT. The Pi edge soak (`sens-pi-soak`) is in this plan
and uses a tagged image from this repository.

## Capability Registry

Every capability appears here exactly once. Status is `planned` when the capability is specified
and has open plan work, or `shipped` when current-state documentation describes it. Row order is
the implementation line.

| # | Capability | Status | How it is evaluated | Implementation |
| --- | --- | --- | --- | --- |
| 1 | `sensor-mesh` | shipped | Decoder unit tests, arm64 footprint gate, `make ci`, 24-hour Pi edge soak | [Current implementation](../impl/current.md) |
| 2 | `device-management` | planned | Registry, provisioning idempotence, downlink, and agent fixture tests | -- |
| 3 | `first-party-firmware` | planned | Golden frames in C, Python, JS; env builds; privacy encoding test | -- |
| 4 | `cross-stack-ci` | planned | `make ci` on full and toolchain-less checkouts; bundle contents | -- |
| 5 | `mesh-transports` | planned | Fixture decode per Meshtastic port; unknown ports skipped | -- |
| 6 | `field-pilot` | planned | Seven-day soak report with measured numbers | -- |
| 7 | `operator-automation` | planned | Seeded flow reaches v1 events; operator feedback summary | -- |
| 8 | `hab-collection` | planned | Simulated ascent replay; track log complete | -- |
| 9 | `rf-sensing` | planned | Synthetic tone found; bounded false-positive anomaly test | -- |

## Extending this specification

A capability gap is a product discovery, not an automatic refusal and not permission for silent
scope growth. Use this lifecycle in order:

1. State the problem in operator or domain terms.
2. Amend the owning section of this specification, including what the capability does not do.
3. Declare the measurement, acceptance signal, and valid negative result before implementation.
4. Add a `planned` registry row with that evaluation.
5. Put tasks under the capability in the implementation line; every task declares `Serves`.
6. Build and evaluate, document available behavior under current state, remove finished plan
   scope, and change the registry row to `shipped` with its implementation link.

When implementation reveals that an existing capability has the wrong boundary, update its section
instead of creating a workaround that the specification cannot explain.

## Specification and plan integrity

The registry and the [implementation plan](../impl/plan.md) are two views of one product:

- every task serves a registered capability and sits in its capability group;
- every capability declares an evaluation;
- every planned capability has at least one open task;
- every shipped capability links to current-state documentation;
- groups follow registry order in each task lane;
- every task declares the fields required by the [planning workflow](../guide/planning-workflow.md);
- lane statuses match whether an agent can finish independently or a human action gates acceptance;
- required tasks precede optional refinements within a capability;
- dependencies name open or recorded tasks, and start dependencies do not form a cycle.
