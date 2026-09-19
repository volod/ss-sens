# ss-sens Implementation Plan

Forward-only: this file describes work that remains. Available behavior belongs in
[current-state documentation](current.md); product behavior and evaluation belong in the
[specification](../design/spec.md). Task fields, statuses, and ordering are defined in the
[planning workflow](../guide/planning-workflow.md).

While ss-sens is staged, repository publish lives in the staging repository's
plan. The Pi edge soak lives here and records numbers against a published image
from the extracted repository. See [Staged work](../design/spec.md#staged-work).

Path reading: `src/ss_sens/` is this package; routes placed under a v1 devices API attach to
`ss-sens serve`; migrations use this repository's runner; conversions that used to live in
the video `sensor_ingest.py` are contract events this service publishes.

## Agent Implementation Tasks

### Device management -- `device-management`

#### device-registry-core

Device inventory, health ledger, and firmware ledger.

- Serves: `device-management` -- [Device management](../design/spec.md#device-management)
- Agent status: CLEAR
- Dependencies: none.
- User-visible outcome: every field device (LoRaWAN node, Meshtastic node, camera,
  HAB payload, gateway) has a registry row with identity, transport, location, firmware
  version (reported vs desired), last-seen, and battery; operators and agents query and
  mutate it over the v1 API.
- Scope boundary: in scope -- PostgreSQL tables `mesh_devices`,
  `mesh_device_events` (append-only ledger: seen/provisioned/flashed/commanded/fault),
  `mesh_firmware` (app, board, version, sha256, url); Pydantic models and store in
  `src/ss_sens/registry/{models,store}.py` (asyncpg, mirroring existing storage
  patterns); router `src/selfsuvis/app/routers/v1/devices.py` with
  `GET/POST /api/v1/devices`, `GET /api/v1/devices/{dev_eui}`,
  `POST /api/v1/devices/{dev_eui}/heartbeat`, `GET /api/v1/devices/{dev_eui}/events`;
  `MqttSubscriber` hook so every decoded uplink upserts last-seen/battery/fw-version.
  Out of scope -- any downlink, provisioning, or UI work. Reuse: migration runner
  `selfsuvis.scripts.migrate_postgres`, v1 router/schema conventions, fake DB pools in
  `tests/support/`.
- Data and artifact paths: migrations add tables; no filesystem artifacts.
- Execution path: `ssv-migrate` applies schema; run API locally (`make up` or
  uvicorn) and exercise endpoints with httpx; unit tests with fake pool.
- Acceptance gates: unit gate green; new tests cover upsert-from-uplink, heartbeat,
  event ledger append, and desired-vs-reported firmware diff; OpenAPI diff gate
  regenerated (`make export-openapi`).
- Documentation target: new `docs/impl/current/device-management.md` (registry
  section); row added to `current.md` Topic Map; `docs/reference/api.md`.

#### chirpstack-provisioning

Declarative device provisioning CLI.

- Serves: `device-management` -- [Device management](../design/spec.md#device-management)
- Agent status: CLEAR
- Dependencies: `device-registry-core`.
- User-visible outcome: `sencoop-provision apply site.yaml` idempotently creates
  ChirpStack applications, device profiles, devices, and OTAA keys from a committed
  manifest, and records each device in the registry -- no UI clicking.
- Scope boundary: in scope -- `src/ss_sens/provision/{manifest,chirpstack_client,cli}.py`;
  manifest schema (site, applications, device_profiles, devices with dev_eui/join_eui/
  app_key/name/tags/gps); ChirpStack REST (`http://localhost:8090`, bearer
  `CHIRPSTACK_API_SECRET`) client with list/create/update; `apply` (idempotent diff),
  `plan` (dry-run diff), `export` (live -> manifest) subcommands; console script in root
  `pyproject.toml`. Out of scope -- gateway provisioning, FUOTA, key generation policy
  (keys come from the manifest or `--gen-keys` writing back to a secrets file under
  `$DATA_DIR/sencoop/provision/`). Reuse: registry store; httpx.
- Data and artifact paths: example manifest committed at
  `config/ss-sens/provision/site-example.yaml`; recorded REST fixtures at
  `tests/assets/chirpstack/*.json`; generated secrets under `$DATA_DIR/sencoop/provision/`.
- Execution path: against live stack -- `make ss-sens-up-min` then
  `sencoop-provision plan|apply config/ss-sens/provision/site-example.yaml`; in CI --
  client tested against recorded fixtures with a fake transport.
- Acceptance gates: unit gate green; `apply` twice produces zero-change second run
  (idempotence test); `plan` output snapshot test; registry rows created.
- Documentation target: `docs/impl/current/device-management.md` (provisioning);
  `docs/ss-sens/sensor-integration.md` gains the manifest path as the primary flow.

#### downlink-command-bus

Commands to devices with an audit trail.

- Serves: `device-management` -- [Device management](../design/spec.md#device-management)
- Agent status: CLEAR
- Dependencies: `device-registry-core`.
- User-visible outcome: `POST /api/v1/devices/{dev_eui}/command` enqueues a LoRaWAN
  downlink (ChirpStack MQTT `application/{app_id}/device/{dev_eui}/command/down`,
  payload `{"devEui","confirmed","fPort","data":base64}`), rate-limited and recorded in
  the device event ledger; Node-RED and agents get a safe command path.
- Scope boundary: in scope -- `src/ss_sens/commands/downlink.py`
  (`DownlinkPublisher` on aiomqtt, per-device token bucket honoring EU868 duty-cycle
  conservatism, default max 1 downlink / 60 s / device, env-tunable); command schema
  (typed commands: `set_interval`, `check_update` fPort 0xF0, `raw`); API route +
  ledger append; deny-by-default `COOP_DOWNLINK_ENABLED=false`. Out of scope --
  multicast, FUOTA, Meshtastic admin messages. Reuse: `MqttSubscriber` connection
  config, v1 router conventions.
- Data and artifact paths: none beyond ledger rows.
- Execution path: live -- enable flag, publish against `make ss-sens-up-min`
  Mosquitto and observe in ChirpStack UI queue; tests -- fake MQTT client asserting
  topic/payload/rate-limit behavior.
- Acceptance gates: unit gate green; rate-limit test (second command within window
  is 429/deferred); base64/fPort encoding golden test; flag-off returns 403.
- Documentation target: `docs/impl/current/device-management.md` (command bus);
  `docs/reference/api.md`; `docs/reference/configuration.md` for new env vars.

#### sencoop-agent-go

Single-binary field gateway agent.

- Serves: `device-management` -- [Device management](../design/spec.md#device-management)
- Agent status: CLEAR
- Dependencies: `device-registry-core`. Optional: artifacts from `esp32-ota-updates` when present.
- User-visible outcome: one static Go binary on any gateway (amd64/arm64) gives
  `sencoop-agent discover` (serial devices by VID:PID -- CP210x/CH340 for ESP32,
  ST-Link for Nucleo, RAK), `sencoop-agent flash --app sensor_node --board heltec_v3
  --port /dev/ttyUSB0` (orchestrates esptool / dfu-util / meshtastic CLIs, verifies
  manifest sha256, records a `flashed` ledger event), `sencoop-agent inventory` and
  `sencoop-agent health --watch` (MQTT status with LWT + registry heartbeats) -- field
  provisioning without a Python environment.
- Scope boundary: in scope -- Go module at `src/ss_sens-agent/` (go >= 1.22; deps
  limited to eclipse/paho.mqtt.golang and go.bug.st/serial), subcommands above,
  `SENCOOP_AGENT_*` env + flags config, `make -C src/ss_sens-agent build test` with
  cross-compile (linux/amd64, linux/arm64) into `.data/sencoop/agent/bin/`. External
  flash tools are orchestrated, not reimplemented: missing tool -> actionable error
  naming the package to install. Out of scope -- implementing flash protocols in Go,
  Windows support, agent self-update (bundle-managed).
- Data and artifact paths: binaries under `.data/sencoop/agent/bin/`; ledger
  events via API.
- Execution path: `go vet ./... && go test ./...` (fake serial enumerator +
  `httptest` registry + fake exec runner); manual smoke against live stack.
- Acceptance gates: `go vet`/`go test` green and wired into `make ci` by
  `ci-cross-stack`; flash flow test proves sha256-mismatch aborts before invoking the
  tool; LWT/health topic golden-tested.
- Documentation target: `docs/impl/current/device-management.md` (agent);
  AGENTS.md layout entry for `src/ss_sens-agent/`.

### First-party firmware -- `first-party-firmware`

#### firmware-workspace

PlatformIO monorepo and the ssvnode wire contract.

- Serves: `first-party-firmware` -- [First-party firmware](../design/spec.md#first-party-firmware)
- Agent status: CLEAR
- Dependencies: none.
- User-visible outcome: `firmware/` builds first-party node firmware for ESP32 and
  STM32 from one `platformio.ini`, and the `ssvnode` payload format is a tested
  three-way contract (C encoder, Python decoder, ChirpStack JS codec) so every future
  node speaks a format the mesh already understands.
- Scope boundary: in scope -- layout `firmware/{platformio.ini, lib/ssvnode/,
  lib/ssvcfg/, apps/, test/test_codec/, scripts/}` with PlatformIO envs `native`
  (host, Unity tests), `heltec_v3` (`board = heltec_wifi_lora_32_V3`, framework
  arduino, RadioLib pinned), `nucleo_wl55jc` (platform ststm32, framework arduino,
  STM32duino + STM32LoRaWAN pinned); `lib/ssvnode/ssvnode_codec.{h,c}` implementing the
  frame below; Python twin `src/ss_sens/sensors/ssvnode_codec.py` wired into
  `lorawan_decoder.decode_chirpstack_uplink` (fPort 10/11 raw-bytes fallback when no
  codec object); JS codec `config/ss-sens/chirpstack/codecs/ssvnode.js`; golden vectors
  `tests/assets/ssvnode/golden_frames.json` (hex frame + expected decoded JSON) consumed
  by both `pio test -e native` and pytest. Out of scope -- any app logic (later tasks),
  OTA, radios beyond library pinning.
  **ssvnode v1 frame (little-endian):** `version:u8=0x01 | flags:u8 | fields in bit
  order` -- bit0 `temperature_c:i16` centi-C; bit1 `humidity_pct:u16` centi-%; bit2
  `co2_ppm:u16`; bit3 `pressure:u16` = (hPa-300)*10; bit4 `battery_v:u8` = V*20; bit5
  `motion:u8` bit0 state, bits1-7 event count; bit6 gps `lat:i32` 1e-7 deg,
  `lon:i32` 1e-7 deg, `alt:u16` = (m+1000)/2; bit7 ext block `type:u8` + payload
  (type 0x01 presence: `wifi_count:u16, ble_count:u16, rssi_avg:i8 dBm,
  window_s:u16`). fPort 10 = telemetry; fPort 11 = status
  `fw_major:u8, fw_minor:u8, fw_patch:u8, reset_reason:u8, uptime_s:u32`.
- Data and artifact paths: committed golden fixtures as above; build output stays
  under `firmware/.pio/` (gitignored).
- Execution path: `pio test -e native` (codec Unity tests); `pio run -e heltec_v3
  -e nucleo_wl55jc` (build-only; no app yet, a minimal blink main per env);
  `make test-unit` runs the Python decoder against the same goldens.
- Acceptance gates: unit gate green; `pio test -e native` green; both device envs
  compile; every golden frame decodes byte-identically in C, Python, and (via committed
  node test script executed with `node`, if available, else documented manual check) JS.
- Documentation target: new `docs/impl/current/firmware.md` (workspace + wire
  contract); AGENTS.md "Current layout" gains the `firmware/` entry.

#### esp32-sensor-node

LoRaWAN class A environmental node.

- Serves: `first-party-firmware` -- [First-party firmware](../design/spec.md#first-party-firmware)
- Agent status: CLEAR
- Dependencies: `firmware-workspace`; provisioning manifest from
  `chirpstack-provisioning` reused for keys.
- User-visible outcome: flash a Heltec V3 and it joins via OTAA, uplinks ssvnode
  telemetry (BME280 temperature/humidity/pressure, PIR motion, battery ADC) every 300 s
  with deep sleep between, and reports a status frame (fPort 11) on boot -- appearing
  automatically in `/site/state` and the registry.
- Scope boundary: in scope -- `firmware/apps/sensor_node/` (main.cpp, RadioLib
  LoRaWAN EU868 OTAA with session persistence across deep sleep, uplink scheduler,
  sensor drivers behind `ssvcfg` compile flags, battery ADC calibration constant);
  `firmware/scripts/gen_secrets.py` generating `include/secrets.h` from the
  provisioning manifest (single source of keys); downlink handler for `set_interval`
  and `check_update` command codes. Out of scope -- OTA transfer itself
  (`esp32-ota-updates`), non-EU bands (config placeholder only).
- Data and artifact paths: golden uplink fixtures appended to
  `tests/assets/ssvnode/golden_frames.json`; built artifact
  `firmware/.pio/build/heltec_v3/firmware.bin`.
- Execution path: `pio run -e heltec_v3` builds; `pio test -e native` covers
  scheduler and encoding logic factored into `lib/`; on-hardware join/uplink is
  deferred to `field-pilot-mesh-site` (human).
- Acceptance gates: unit gate + native tests green; build succeeds with all sensor
  flags on and off; encoded fixture from app-level code decodes via Python decoder in
  pytest; deep-sleep session persistence logic unit-tested on native env with fake NVS.
- Documentation target: `docs/impl/current/firmware.md` (sensor node app);
  `docs/ss-sens/sensor-integration.md` gains "first-party node" section.

#### stm32wl-sensor-node

Long-endurance STM32WL node.

- Serves: `first-party-firmware` -- [First-party firmware](../design/spec.md#first-party-firmware)
- Agent status: CLEAR
- Dependencies: `firmware-workspace`, `esp32-sensor-node` (reuses app structure).
- User-visible outcome: the same ssvnode telemetry from a Nucleo-WL55JC using the
  integrated SX126x radio and STOP2 low-power mode -- the multi-year-battery variant of
  the sensor node for permanent installs.
- Scope boundary: in scope -- `firmware/apps/sensor_node_wl/` on the
  `nucleo_wl55jc` env (STM32LoRaWAN library, RTC-driven wakeup, STOP2 between uplinks,
  same ssvnode codec and secrets generation); shared app logic extracted to
  `firmware/lib/ssvapp/` so ESP32 and STM32 mains stay thin. Out of scope -- MCUboot /
  secure boot (future task if demanded), custom PCBs.
- Data and artifact paths: as `esp32-sensor-node`.
- Execution path: `pio run -e nucleo_wl55jc`; `pio test -e native` for shared
  `ssvapp` logic.
- Acceptance gates: unit gate + native tests green; both node apps build from the
  shared lib with no duplicated scheduler/codec code (checked by review, enforced by
  lib layout); documented measured-vs-budgeted sleep current table template (numbers
  filled by human field task).
- Documentation target: `docs/impl/current/firmware.md` (WL variant + power budget).

#### esp32-ota-updates

Firmware publish and WiFi OTA loop.

- Serves: `first-party-firmware` -- [First-party firmware](../design/spec.md#first-party-firmware)
- Agent status: CLEAR
- Dependencies: `device-registry-core`, `esp32-sensor-node`.
- User-visible outcome: `sencoop-firmware publish firmware/.pio/build/heltec_v3/
  firmware.bin --app sensor_node --board heltec_v3 --version 1.2.0` stages a signed
  (sha256) artifact; WiFi-capable nodes told `check_update` fetch the manifest, update,
  and the registry shows reported version converging to desired.
- Scope boundary: in scope -- publisher CLI `src/ss_sens/firmware/publish.py`
  writing `$DATA_DIR/sencoop/firmware/<app>/<board>/{firmware.bin,manifest.json}`
  (manifest: app, board, version, sha256, size, url) and upserting `mesh_firmware`;
  nginx proxy static location `/firmware/` serving that directory (config under
  `config/ss-sens/`); device side -- HTTPUpdate flow in `ssvapp` triggered by boot
  check or `check_update` downlink, guarded by sha256 verify and version compare;
  registry endpoint `GET /api/v1/devices/updates-pending`. Out of scope -- LoRaWAN
  FUOTA (explicitly deferred; revisit as its own task when a WiFi-less fleet demands
  it), STM32 DFU (agent task `sencoop-agent-go` covers wired flashing).
- Data and artifact paths: `$DATA_DIR/sencoop/firmware/` tree; manifest golden
  fixtures under `tests/assets/firmware/`.
- Execution path: publish CLI against a temp `$DATA_DIR` in tests; end-to-end on
  hardware deferred to `field-pilot-mesh-site`.
- Acceptance gates: unit gate green; publish is idempotent and refuses
  version-downgrade without `--force`; manifest schema round-trips; registry
  desired/reported diff endpoint tested.
- Documentation target: `docs/impl/current/device-management.md` (OTA);
  `docs/ss-sens/distribution.md`.

#### esp32-sigint-scanner

Privacy-preserving presence sensing.

- Serves: `first-party-firmware` -- [First-party firmware](../design/spec.md#first-party-firmware)
- Agent status: CLEAR
- Dependencies: `firmware-workspace`, `esp32-sensor-node`. Cross-lane note: enabling ingestion
  by default is gated by human task `sigint-privacy-review`; until then
  `COOP_PRESENCE_INGEST=false`.
- User-visible outcome: a scanner node counts nearby WiFi probe-request emitters
  and BLE advertisers per window (counts and coarse RSSI only -- no identifiers ever
  leave the device) and uplinks an ssvnode ext-presence block; with the flag on, counts
  appear in `/site/state` and feed the threat layer as `rf_presence` events.
- Scope boundary: in scope -- `firmware/apps/presence_scanner/` (esp_wifi
  promiscuous mgmt-frame filter + NimBLE scan; per-window dedupe via salted truncated
  SHA-256 where the salt derives from device key + window counter and is discarded --
  nothing persistent, `SSV_PRIVACY_COUNTS_ONLY=1` is compile-default and the only
  shipped mode); ingestion -- decoder aliases `wifi_count`, `ble_count`, `rssi_avg` and
  `sensor_ingest.sensor_reading_to_event` emitting
  `SensorEvent(sensor_type="rf_presence")` behind `COOP_PRESENCE_INGEST`. Out of scope
  -- MAC vendor analysis, per-device tracking, deauth or any active transmission
  (passive receive only), channel hopping tuning beyond a fixed default list.
- Data and artifact paths: golden ext-block fixtures in
  `tests/assets/ssvnode/golden_frames.json`.
- Execution path: `pio run -e heltec_v3` (scanner env variant); native tests for
  window/dedupe/encode logic with injected fake scan results; pytest for ingestion
  flag-on/flag-off behavior.
- Acceptance gates: unit gate + native tests green; a code-level assertion/test
  proves no field wider than counts/RSSI is encodable in the presence block; flag-off
  drops events with a single startup log line.
- Documentation target: `docs/impl/current/firmware.md` (scanner);
  `docs/operations/` privacy note stub referencing the pending review.

### Cross-stack CI -- `cross-stack-ci`

#### ci-cross-stack

One gate across Python, firmware, Go, and bundles.

- Serves: `cross-stack-ci` -- [Cross-stack CI](../design/spec.md#cross-stack-ci)
- Agent status: CLEAR
- Dependencies: none. Optional: `firmware-workspace`, `sencoop-agent-go` (jobs activate per
  path; the workflow can land earlier with only Python jobs).
- User-visible outcome: every PR runs a path-filtered matrix -- Python lint+unit,
  firmware builds + native tests, Go vet+test+cross-build, FPGA lint -- and one local
  command (`make ci`) reproduces it; offline release bundles can embed firmware and
  agent artifacts, so a field kit ships from one build.
- Scope boundary: in scope -- `.github/workflows/ci.yml` with jobs: `python`
  (ruff + `pytest tests/unit`), `firmware` (paths `firmware/**`: `pio run` all envs +
  `pio test -e native`, PlatformIO cache), `go-agent` (paths `src/ss_sens-agent/**`:
  vet, test, cross-build, upload artifacts), `fpga-lint` (TCL/py static checks only --
  never Vivado); Makefile additions `make ci` (lint + test-unit + firmware native
  tests when `pio` is on PATH + agent tests when `go` is on PATH; each missing
  toolchain prints one warning line and skips), `make firmware`, `make agent`;
  `scripts/ss-sens/ss-sens-release.sh --with-firmware --with-agent` embedding
  `$DATA_DIR/sencoop/firmware/` manifests and agent binaries into the offline bundle
  with a bundle manifest listing. Out of scope -- hardware-in-the-loop runners
  (revisit after the field pilot), nanochat/sslm CI, bitstream builds in CI.
- Data and artifact paths: CI artifacts (firmware .bin, agent binaries); bundle
  output as today under the release script's output tree.
- Execution path: `make ci` locally; `actionlint` on the workflow when available;
  a bundle build with both flags and an inspection of its manifest.
- Acceptance gates: `make ci` green on a full checkout and on a toolchain-less
  checkout (skips, does not fail); workflow triggers verified by path-filter unit
  cases in a dry-run; bundle contains the declared artifacts.
- Documentation target: `docs/impl/current/build-ci-test.md` (rewrites the "Known
  gaps" section); `docs/ss-sens/distribution.md`.

### Mesh transports -- `mesh-transports`

#### meshtastic-mesh-bridge

LoRa mesh transport ingestion.

- Serves: `mesh-transports` -- [Mesh transports](../design/spec.md#mesh-transports)
- Agent status: CLEAR
- Dependencies: `device-registry-core`.
- User-visible outcome: stock-firmware Meshtastic nodes (with an MQTT-uplink
  gateway node pointed at ss-sens-mosquitto, topic root `msh`) appear as registry devices
  and mesh members: positions and telemetry land in `/site/mesh` and `/site/state`,
  text messages land in the device event ledger -- infrastructure-less coverage beyond
  LoRaWAN star range.
- Scope boundary: in scope -- `src/ss_sens/sensors/meshtastic_bridge.py`
  subscribing `msh/#`, decoding `ServiceEnvelope` protobufs via the `meshtastic` pip
  package (added to the `sencoop` extra), handling POSITION_APP, TELEMETRY_APP,
  NODEINFO_APP, TEXT_MESSAGE_APP; mapping to registry (`transport="meshtastic"`),
  `SensorMeshFusion` nodes, and `SensorEvent(sensor_type="mesh")`; Mosquitto ACL user
  `meshtastic`; provisioning helper `sencoop-mesh-provision` that shells to the
  `meshtastic` CLI over serial to set region/channel/MQTT (documented; hardware run
  deferred to field pilot). Out of scope -- acting as a mesh router ourselves, custom
  Meshtastic firmware, encrypted-channel key management beyond documenting defaults.
- Data and artifact paths: captured envelope fixtures (base64) under
  `tests/assets/meshtastic/`.
- Execution path: pytest against fixtures with fake MQTT; live smoke via
  `mosquitto_pub` replay against `make ss-sens-up-min`.
- Acceptance gates: unit gate green; each handled port number has a
  fixture-decode test; unknown ports are counted and skipped without error; registry
  upsert covered.
- Documentation target: `docs/impl/current.md` (transport matrix
  gains meshtastic); `docs/ss-sens/sensor-integration.md`.

### Operator automation -- `operator-automation`

#### node-red-automation

Operators need to edit automation without code.

- Serves: `operator-automation` -- [Operator automation](../design/spec.md#operator-automation)
- Agent status: RUN NEEDED
- Dependencies: none. Optional: example flows use `downlink-command-bus` when present.
- User-visible outcome: the ss-control `automation` profile starts a pinned Node-RED with seeded
  flows: (1) `application/#` uplinks normalized and POSTed to `POST /api/v1/events/lorawan`;
  (2) Frigate person-detection -> example downlink command; (3) a broker/stack health dashboard.
  Operators edit automation without code.
- Scope boundary: in scope -- Node-RED service (image `nodered/node-red` pinned by digest,
  volume `$DATA_DIR/ss-control/nodered/`) in the ss-control compose project under profile
  `automation`, reachable only through the ss-control proxy and identity provider;
  flows-as-code `config/nodered/flows.json` + `settings.js` (adminAuth through the identity
  provider and `credentialSecret` from env) in ss-control; Mosquitto ACL user `nodered` in
  ss-sens (read `application/#`, `frigate/#`; write `application/+/device/+/command/down`) with
  a site-CA client certificate; Make target `up-automation` in ss-control. Out of scope --
  custom Node-RED nodes, dashboards beyond the seeded three. Reuse: ACL/user tooling
  `scripts/ss-sens/ss-sens-mqtt-users.sh`, ss-control certificate enrolment.
- Data and artifact paths: ss-control `config/nodered/` (committed flows/settings);
  `$DATA_DIR/ss-control/nodered/` runtime.
- Execution path: `make up-automation` in ss-control with the ss-sens stack running; verify
  flow 1 by publishing a fixture uplink with `mosquitto_pub` and asserting the v1 event lands
  (`GET /api/v1/site/state`).
- Acceptance gates: unit gate green (compose/config lint via existing tests
  pattern); an integration-marked test drives fixture-publish -> API-event assertion;
  flows.json committed and loads without missing nodes.
- Documentation target: new `docs/impl/current/automation-platforms.md`;
  `docs/ss-sens/getting-started.md` profile table.

#### openremote-asset-sync (optional)

ChirpStack devices as OpenRemote assets. This task exists only if `site-control-evaluation` keeps
OpenRemote; otherwise that evaluation removes it.

- Serves: `operator-automation` -- [Operator automation](../design/spec.md#operator-automation)
- Agent status: RUN NEEDED
- Dependencies: `device-registry-core`, `chirpstack-provisioning`.
- User-visible outcome: `sencoop-or-sync --watch` keeps OpenRemote assets in step
  with the registry/ChirpStack: one asset per device with attributes (battery,
  temperature, last-seen, position) updating live; operators get dashboards and alarms
  in the platform they already run.
- Scope boundary: in scope -- `src/ss_sens/openremote/{client,asset_sync}.py`
  (Keycloak service-user token via client-credentials grant, OpenRemote Manager REST
  asset CRUD + attribute writes), mapping table registry-device -> asset type/attrs,
  `--once` and `--watch` (default 300 s) modes, console script `sencoop-or-sync`.
  Out of scope -- OpenRemote rules/dashboards content (human task
  `operator-dashboard-acceptance`), MQTT agent-link configuration inside OR. Reuse:
  registry store, httpx, recorded-fixture test pattern from provisioning.
- Data and artifact paths: fixtures `tests/assets/openremote/*.json`.
- Execution path: live -- ss-control `openremote` profile then
  `sencoop-or-sync --once`; tests against recorded fixtures with fake transport.
- Acceptance gates: unit gate green; sync is idempotent (second `--once` is
  zero-change); attribute update path golden-tested; token refresh on 401 covered.
- Documentation target: `docs/impl/current/automation-platforms.md` (OpenRemote
  section); `docs/ss-sens/integration.md`.

### HAB collection -- `hab-collection`

#### hab-telemetry-stack

HAB payload, ground station, and live track.

- Serves: `hab-collection` -- [HAB collection](../design/spec.md#hab-collection)
- Agent status: CLEAR
- Dependencies: `firmware-workspace`, `esp32-sensor-node`. Cross-lane note: real-flight evidence
  comes from human task `hab-flight-campaign`; all acceptance here is simulation-based.
- User-visible outcome: a high-altitude balloon payload streams position/altitude/
  environment over long-range LoRa P2P to a ground station that publishes
  `hab/telemetry/{callsign}` into the mesh; the flight appears live in `/site/state`
  and `/site/mesh` with an ascent/burst/descent/landed state machine -- region-scale
  collection from a hobby-launch budget.
- Scope boundary: in scope -- firmware `firmware/apps/hab_tracker/` (ESP32 +
  u-blox GPS with UBX airborne <1g dynamic model set at boot and re-verified, BME280,
  LoRa P2P TX duty-cycle-aware default 1 frame / 30 s) and `firmware/apps/hab_gateway/`
  (RX-only, frames -> JSON lines over USB serial); ground side
  `src/ss_sens/sensors/hab_ground_station.py` (pyserial reader, CRC check, MQTT
  publish, registry heartbeat) and flight state machine (vertical-rate thresholds
  +2 / -3 m/s with hysteresis); simulator CLI `sencoop-hab-sim` replaying a committed
  ascent CSV to a pty or MQTT. **HAB v1 frame (32 bytes, little-endian):**
  `sync:u16="SV" | ver:u8 | callsign:6xASCII | counter:u16 | gps_tow_s:u32 | lat:i32
  1e-7 | lon:i32 1e-7 | alt_m:u16 | speed_mps:u8 | sats:u8 | temp_c:i8 | batt:u8=V*20
  | state:u8 | crc16_ccitt:u16`. Out of scope -- cutdown control, landing prediction
  (note tawhiri integration as possible future task), APRS/amateur-radio modes,
  redundant trackers.
- Data and artifact paths: sim flight CSV `tests/assets/hab/ascent_sim.csv`;
  flight logs `$DATA_DIR/sencoop/hab/<flight_id>/track.jsonl`.
- Execution path: `pio run -e heltec_v3` for both apps; `sencoop-hab-sim --mqtt`
  end-to-end against `make ss-sens-up-min`; pytest on frame codec, CRC, state machine.
- Acceptance gates: unit gate + native tests green; sim replay produces a
  monotonic track in `/site/state`, correct burst detection at the CSV apex, and a
  complete `track.jsonl`; frame encode/decode golden-tested C-vs-Python.
- Documentation target: new `docs/impl/current/hab.md`; launch checklist lives
  with the human task.

### RF sensing -- `rf-sensing`

#### xc7z020-rf-frontend

FPGA spectral front-end, simulation first.

- Serves: `rf-sensing` -- [RF sensing](../design/spec.md#rf-sensing)
- Agent status: CLEAR
- Dependencies: `firmware-workspace` (layout conventions only). Cross-lane note: hardware
  verification is gated by human task `zynq-hardware-bringup`; every agent-side gate runs in
  simulation.
- User-visible outcome: a PYNQ-Z2 (XC7Z020) node computes averaged RF spectra in
  fabric (AXI DMA + FFT LogiCORE) and publishes
  `sensors/rf_spectrum/{node}` JSON (`center_hz, span_hz, bins[], noise_floor_dbm,
  peaks[]`) into the mesh; without hardware, the identical publisher runs in `--sim`
  mode over recorded IQ, so the analytics stack develops against real message shapes.
- Scope boundary: in scope -- `firmware/fpga/zynq7020/` with committed Vivado
  2022.1 block-design TCL + `Makefile bitstream` running inside a pinned container
  (`firmware/fpga/docker/Dockerfile.vivado`; the Vivado installer/license is a human
  prerequisite documented there -- CI never builds bitstreams); PS-side
  `firmware/fpga/zynq7020/pynq/rf_spectrum_publisher.py` (PYNQ overlay load, DMA
  capture, Welch-style averaging, peak extraction, MQTT publish) with `--sim` numpy
  path over `tests/assets/rf/iq_sample.npz`; subscriber-side handling of
  `sensors/rf_spectrum/#` -> `SensorEvent(sensor_type="rf_spectrum")`. Out of scope --
  RF front-end hardware selection (test vectors from PS memory first), demodulation,
  direction finding, Vitis AI / neural overlays.
- Data and artifact paths: IQ fixture `tests/assets/rf/iq_sample.npz`; bitstreams
  land under `$DATA_DIR/sencoop/fpga/` (never committed; sha256 recorded in
  `mesh_firmware`).
- Execution path: `python firmware/fpga/zynq7020/pynq/rf_spectrum_publisher.py
  --sim --mqtt localhost` against `make ss-sens-up-min`; pytest on peak extraction and
  message schema; bitstream build documented as heavy host-only step.
- Acceptance gates: unit gate green; sim publisher emits schema-valid messages at
  the configured rate; known synthetic tone in the IQ fixture is found within one bin;
  ingestion test covers the new sensor_type.
- Documentation target: `docs/impl/current/firmware.md` (FPGA section);
  `docs/ss-sens/sensor-integration.md`.

#### rf-threat-analytics

Baselines, anomalies, and the RF field map.

- Serves: `rf-sensing` -- [RF sensing](../design/spec.md#rf-sensing)
- Agent status: CLEAR
- Dependencies: `esp32-sigint-scanner` and/or `xc7z020-rf-frontend` and/or
  `meshtastic-mesh-bridge` (any RF-ish source); `device-registry-core`.
- User-visible outcome: `GET /site/rf` returns per-node RF baselines (presence
  counts, band power), current anomaly scores, and an optional Gaussian-process field
  map over the site grid; sustained anomalies feed the threat aggregator as
  `ThreatEvent(sensor_type="rf")` -- turning point RF readings into spatial risk, the
  future-directions "environmental fields" theme made concrete.
- Scope boundary: in scope -- `src/ss_sens/mesh/rf_baseline.py` (per-node,
  per-band EWMA baseline keyed by hour-of-day, robust z-score anomaly with env-tunable
  thresholds and a minimum-duration gate), GPR field estimate
  (`sklearn.gaussian_process`, optional dep in the `sencoop` extra; grid over the site
  bbox at the existing ~110 m sector resolution; mean + uncertainty per cell), the
  `/site/rf` route, and threat-aggregator wiring. Out of scope -- emitter
  localization/DF, classification of signal types, cross-mission persistence (that is
  the future `global-threat-persistence` theme).
- Data and artifact paths: synthetic series fixtures
  `tests/assets/rf/baseline_series.json`.
- Execution path: pytest-driven; live smoke by replaying fixtures through MQTT.
- Acceptance gates: unit gate green; injected anomaly is flagged and a quiet
  series is not (bounded false-positive test); GPR path degrades gracefully when
  sklearn is absent; endpoint schema tested.
- Documentation target: `docs/impl/current.md` (RF analytics);
  `docs/learning_path/18_future_directions.md` updated to mark field models as partially
  available.

## Human-Assisted Tasks

### Sensor mesh -- `sensor-mesh`

#### sens-pi-soak

Only a real Pi shows whether the edge profile fits its resource budget.

- Serves: `sensor-mesh` -- [Sensor mesh](../design/spec.md#sensor-mesh)
- Agent status: BLOCKED BY HUMAN
- Dependencies: none. Cross-lane note: acceptance uses a published image from the
  extracted repository, not the staged tree.
- User-visible outcome: measured CPU, memory, and restart numbers for the ss-sens `edge` profile on
  a Raspberry Pi over 24 hours set the documented minimum hardware.
- Human step: after the staging repository publishes volod/ss-sens, provide a Raspberry Pi 4 or 5
  on the LAN with Docker, start the `edge` profile from that published image, and leave it running
  for 24 hours.
- Scope boundary: the agent supplies a soak script that replays fixture uplinks at a configured
  rate and samples `docker stats` and restart counts; field hardware and radio are out of scope.
  Out of scope -- running the soak against a locally tagged staging image as the acceptance run.
- Data and artifact paths: soak output under `$DATA_DIR/ss-sens/soak/<run-id>/`.
- Execution path: from the extracted repository, pull or build the published image, set
  `SS_SENS_IMAGE`, `make ss-sens-up-edge` on the Pi, then the soak script.
- Acceptance gates: 24 hours without service restarts; memory growth bounded; numbers recorded
  against a published image. Valid negative result: the measured numbers raise the minimum
  hardware (8 GB Pi 5 or nettop).
- Documentation target: [deployment.md](current/deployment.md).

### First-party firmware -- `first-party-firmware`

#### sigint-privacy-review

Privacy sign-off for presence sensing.

- Serves: `first-party-firmware` -- [First-party firmware](../design/spec.md#first-party-firmware)
- Agent status: HUMAN-GATED
- Dependencies: `esp32-sigint-scanner` (built, flag-off). Blocks: flipping
  `COOP_PRESENCE_INGEST` default and any claim of production presence sensing.
- User-visible outcome: a recorded decision that counts-only presence sensing is
  acceptable for the deployment jurisdictions, with the boundary conditions written
  down where operators will see them.
- Human step: owner/legal review and sign-off of the assessment; jurisdictional
  check (GDPR-style device-identifier rules differ even for hashed, discarded scans).
- Scope boundary: agent-buildable support -- draft assessment at
  `docs/operations/sigint-privacy.md` (data captured, retention = none beyond counts, salt
  lifecycle, threat model), plus the config plumbing already landed with the scanner task.
- Data and artifact paths: `docs/operations/sigint-privacy.md`.
- Execution path: review of the draft assessment.
- Acceptance gates: signed-off doc committed; default flip lands as a one-line
  config change referencing the doc.
- Documentation target: `docs/operations/sigint-privacy.md`;
  `docs/reference/configuration.md`.

### Field pilot -- `field-pilot`

#### field-pilot-mesh-site

One real site, seven-day soak.

- Serves: `field-pilot` -- [Field pilot](../design/spec.md#field-pilot)
- Agent status: BLOCKED BY HUMAN
- Dependencies: `esp32-sensor-node`, `meshtastic-mesh-bridge`,
  `sencoop-agent-go`, `chirpstack-provisioning`. Optional: `node-red-automation` (recommended).
- User-visible outcome: a documented reference deployment: 3 sensor nodes,
  2 Meshtastic nodes, 1 LoRaWAN gateway, 1 camera, 1 nettop running the stack --
  with a seven-day soak report (uptime, packet loss, battery slope, at least one
  camera+sensor fused incident) that becomes the honesty benchmark for the docs.
- Human step: hardware purchase and assembly, EU868 duty-cycle compliance check,
  antenna/node placement, physical install, and the seven-day watch.
- Scope boundary: agent-buildable support -- BOM + install runbook
  `docs/runbooks/field-pilot.md`; `ss-sens-analytics soak --days 7` report additions
  (per-device uptime, loss, battery regression) in `src/ss_sens/analytics/`.
- Data and artifact paths: soak report under `docs/ss-sens/`.
- Execution path: `ss-sens-analytics soak --days 7` over the pilot's logs.
- Acceptance gates: soak report committed under `docs/ss-sens/` with real numbers;
  every deviation filed as a new forward task.
- Documentation target: `docs/runbooks/field-pilot.md`;
  `docs/impl/current.md` sizing section updated with measured data.

### Operator automation -- `operator-automation`

#### operator-dashboard-acceptance

Operators judge the pane of glass.

- Serves: `operator-automation` -- [Operator automation](../design/spec.md#operator-automation)
- Agent status: HUMAN-GATED
- Dependencies: `node-red-automation`, `field-pilot-mesh-site`. Optional: `openremote-asset-sync` when OpenRemote is kept.
- User-visible outcome: the operator pane selected by `site-control-evaluation` (Grafana and
  Node-RED, or OpenRemote) that real operators used for a week and rated workable -- the
  "satisfaction for users, planners, engineers, operators, and owners" claim backed by evidence.
- Human step: at least two operators use the dashboards for a week during the
  soak; structured feedback session; sign-off that alarms are neither silent nor noisy.
- Scope boundary: agent-buildable support -- seeded dashboard and asset templates, feedback form
  template in docs, and fixes for the feedback that lands as concrete issues.
- Data and artifact paths: feedback summary under `docs/impl/current/`.
- Execution path: a week of operator use during `field-pilot-mesh-site`.
- Acceptance gates: feedback summary committed; every accepted item either fixed
  or filed as a forward task.
- Documentation target: `docs/impl/current/automation-platforms.md` (operator
  acceptance section).

### HAB collection -- `hab-collection`

#### hab-flight-campaign

One recovered flight.

- Serves: `hab-collection` -- [HAB collection](../design/spec.md#hab-collection)
- Agent status: HUMAN-GATED
- Dependencies: `hab-telemetry-stack`.
- User-visible outcome: one legal, recovered HAB flight with continuous telemetry
  logged into site state and a post-recovery `ssv` mission run over payload video.
- Human step: regulatory clearance (airspace notification/permission per
  jurisdiction), launch logistics, chase and recovery.
- Scope boundary: agent-buildable support -- launch checklist `docs/runbooks/hab-launch.md`;
  `sencoop-hab-sim preflight` validation (GPS airborne mode confirmed, TX interval
  legal for band, battery margin vs predicted flight time, ground-station lock).
- Data and artifact paths: flight track under `$DATA_DIR/sencoop/hab/<id>/`.
- Execution path: flight, recovery, then the `hab-mission-pipeline` command over payload video.
- Acceptance gates: flight track archived under `$DATA_DIR/sencoop/hab/<id>/` and
  summarized in docs; mission run artifacts produced; lessons filed as forward tasks.
- Documentation target: `docs/impl/current/hab.md` (flight evidence section);
  `docs/runbooks/hab-launch.md`.

### RF sensing -- `rf-sensing`

#### zynq-hardware-bringup

XC7Z020 bench validation.

- Serves: `rf-sensing` -- [RF sensing](../design/spec.md#rf-sensing)
- Agent status: BLOCKED BY HUMAN
- Dependencies: `xc7z020-rf-frontend`. Blocks: hardware-verified claims for
  the FPGA front-end.
- User-visible outcome: the spectral overlay running on a physical PYNQ-Z2,
  matching the simulation within stated tolerance on a loopback test vector.
- Human step: board procurement, Vivado install/license acceptance in the pinned
  container, bench bring-up (boot PYNQ image, load overlay, run loopback IQ).
- Scope boundary: agent-buildable support -- bring-up runbook `docs/runbooks/pynq-z2.md`;
  sim-vs-hardware comparison script emitting a pass/fail delta report.
- Data and artifact paths: comparison report; bitstreams under `$DATA_DIR/sencoop/fpga/`.
- Execution path: bench bring-up, then the comparison script.
- Acceptance gates: comparison report committed (per-bin power delta within
  tolerance on the synthetic tone); bitstream sha256 recorded in `mesh_firmware`.
- Documentation target: `docs/impl/current/firmware.md` (FPGA verified matrix).

## Future-task candidates

Deliberately not scheduled yet: `lorawan-fuota` (fleet OTA without WiFi), `mcuboot-secure-boot`
(STM32 signed boot), `hab-landing-prediction` (tawhiri integration), `rust-sdr-dsp`,
`hil-runner` (self-hosted hardware-in-the-loop CI after the field pilot), and
`sens-name-cleanup` (rename remaining `COOP_*` env vars).
