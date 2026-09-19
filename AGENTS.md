# AGENTS.md project rules

This file is the canonical instruction source for every coding agent in this repository.
Tool-specific files (`CLAUDE.md`, `GEMINI.md`, `.codex`, `.cursor/rules/project-rules.mdc`)
link here and keep only integration-specific routing.

## Development guardrails

- **Git:** Do not commit, push, rewrite history, or revert user changes unless explicitly asked.
- **Scope:** Preserve unrelated work. Diagnose without changing code when the request is diagnostic.
- **Python:** Support Python 3.11 or newer (Raspberry Pi OS Bookworm ships 3.11). Use `uv`,
  `uv.lock`, and `pyproject.toml` for dependency management. Use Make targets for standard
  workflows. Before a direct `uv` command, source `scripts/shared/common.sh` and run
  `ssc_load_env`.
- **Typing:** Do not add `from __future__ import annotations`; use normal annotations and
  `TYPE_CHECKING` imports when needed.
- **Paths:** Never hardcode machine-specific absolute paths. Resolve from the project root and
  honor `.env` and `DATA_DIR`; the uv and tool caches live under `$DATA_DIR`.
- **Secrets:** Never commit credentials or include them in logs, tests, fixtures, or documentation.
- **Dependencies:** Add the smallest justified dependency. Update `uv.lock` in the same change.
- **ASCII:** Use ASCII in logs, docs, comments, and generated shell output.
- Pin ss-common at git tag `v0.1.0` (`ss-common[mqtt,web]`). Do not take a path sibling.

## Package rules

- One distribution, `ss-sens`, with import package `src/ss_sens/`. Tests live under `tests/`.
- Base dependencies are `aiomqtt`, `pydantic`, `httpx`, `uvicorn`, and `ss-common[mqtt,web]`.
  Analytics (`pandas`, `jinja2`, `rich`, `docker`) stay behind the `analytics` extra.
  The footprint gate forbids torch, transformers, onnxruntime, ctranslate2, and streamlit
  on `aarch64-unknown-linux-gnu` (and x86_64). The runtime image is CPU-only even when
  built on a CUDA host.
- `COOP_*` env vars and MQTT topic strings stay. Do not rename them in this repository.
- Runtime data belongs under `$DATA_DIR` (default `.data/` in this project). Bind mounts for the
  compose stack live under `$DATA_DIR/coop/` (`COOP_*` layout). Never write a module-local
  `.data/` inside `src/`.
- Shared shell behavior belongs in `scripts/shared/common.sh`. Ops entrypoints live under
  `scripts/ss-sens/`.

## Current layout

- Package: `src/ss_sens/` (config, MQTT subscriber, LoRaWAN decoder, contract publisher, rolling
  sensor state, mesh fusion, FastAPI `serve`, analytics CLI)
- Compose: `docker/ss-sens/docker-compose.ss-sens.yml`
- Config: `config/ss-sens/`
- Ops scripts: `scripts/ss-sens/`
- Operator docs: `docs/ss-sens/`

## Usual commands

- `make ci` — locked install, lint, doc-link and spec-plan checks, footprint gate, unit tests
- `make footprint` — resolve the base install for aarch64 and x86_64; fail on ML stacks
- `make image` — multi-arch CPU-only image, recorded sizes, QEMU `/site/sensors`
- `make ss-sens-up` / `make ss-sens-up-min` — bootstrap and start LoRaWAN + MQTT + `ss-sens serve`
- `make ss-sens-up-edge` — Pi profile (LoRaWAN + MQTT + ss-sens + node-exporter)
- `make ss-sens-down`, `make ss-sens-logs`, `make ss-sens-status`
- `python -m ss_sens serve` — FastAPI on `COOP_HTTP_PORT` (8081)

## Tests and quality

- Add or update tests with every behavior change.
- `make ci` is the required gate (includes the arm64 footprint gate). Stack tests
  (`make test-stack`) need Docker and `make ss-sens-up-min`; they are not part of
  `make ci`. `make image` is the multi-arch / QEMU run; it is not part of `make ci`.
- Fix findings at their source; do not weaken checks to fit new code.

## Documentation lifecycle

| Question | Source of truth |
| --- | --- |
| What should the product do? | `docs/design/spec.md` (capability registry, boundaries, evaluation) |
| What work remains? | `docs/impl/plan.md` (forward-only) |
| What exists and where? | `docs/impl/current.md` and `docs/impl/current/` |
| What happened to a finished task? | `docs/impl/records/` |
| How is work performed? | `docs/guide/` and this file |

`docs/impl/plan.md` is FORWARD-ONLY: it contains only work that remains. Delivered behavior lives
under `docs/impl/current.md`. Product behavior and boundaries live in `docs/design/spec.md`.

After every product or developer-facing change, before reporting completion:

1. Record what exists in the narrowest current-state page.
2. Remove the completed task from `docs/impl/plan.md`; retain only residual future work.
3. Route anything surfaced during implementation exactly once: a chore is done now or dropped;
   an audit of the work just produced is performed as part of completion; more work for a
   registered capability becomes a task, `(optional)` when it is a refinement; a new product
   capability follows "Extending this specification" in `docs/design/spec.md` first.
4. Update current-doc indexes when adding a page and run `make lint-doc-links`.
5. Compare plan task counts before and after and state which capabilities moved.

Do not put completion notes, dates, measurements, or history in the plan.

## Task lanes and integrity

The plan has two lanes, **Agent Implementation Tasks** (`CLEAR`, `RUN NEEDED`) and
**Human-Assisted Tasks** (`BLOCKED BY HUMAN`, `HUMAN-GATED`, plus a `Human step` field). Task
fields, ordering, dependencies, and records are defined in the
[planning workflow](docs/guide/planning-workflow.md). `make lint-spec-plan` enforces them; fix
document disagreements when it fails and do not loosen the checker. `make plan-status` names the
next eligible task per lane.

## Completion discipline

Before declaring a plan task complete: keep a task record under `docs/impl/records/`, run the
declared tests and `make ci`, update current docs, remove finished plan scope, and inspect
`git status`. Confirm that only intended files changed and that no process, port, temporary
scaffold, or external resource started by the work remains active. Runtime artifacts under
`DATA_DIR` are evidence; keep them unless the task says otherwise.
