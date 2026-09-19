#!/usr/bin/env bash
# Bootstrap the ss-sens stack: ensure `.data/.env`, create bind-mount dirs,
# generate Mosquitto TLS + MQTT users if missing, then run docker compose.
#
# Usage:
#   ./scripts/ss-sens/ss-sens-bootstrap.sh
#   APP_ENV=dev ./scripts/ss-sens/ss-sens-bootstrap.sh up -d
#   ./scripts/ss-sens/ss-sens-bootstrap.sh logs -f

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../shared/common.sh"
project_cd_root

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  cat <<'EOF'
Usage: ./scripts/ss-sens/ss-sens-bootstrap.sh [compose-args...]

Bootstrap the ss-sens stack and then delegate to ss-sens-compose.
If no arguments are passed, this runs: `./scripts/ss-sens/ss-sens-compose.sh up -d`

Examples:
  ./scripts/ss-sens/ss-sens-bootstrap.sh
  APP_ENV=dev ./scripts/ss-sens/ss-sens-bootstrap.sh up -d
  ./scripts/ss-sens/ss-sens-bootstrap.sh logs -f
EOF
  exit 0
fi

ENV="$(project_default_app_env)"

# Generate .data/.env from template if missing
if [[ ! -f "$(project_env_file)" ]]; then
  project_log "Creating .data/.env from env/${ENV}.env (first run)"
  "$PROJECT_ROOT_DIR/scripts/ss-sens/ss-sens-env.sh" "$ENV"
fi

# Ensure bind-mount directories exist
"$PROJECT_ROOT_DIR/scripts/ss-sens/ss-sens-data-dirs.sh"

project_load_env_optional
_DATA_DIR="$(project_data_dir)"

# Generate Mosquitto TLS certs if missing
if [[ ! -f "$_DATA_DIR/coop/mosquitto/certs/server.key" ]]; then
  project_log "Generating Mosquitto TLS certs"
  HOST="${OR_HOSTNAME:-localhost}"
  "$PROJECT_ROOT_DIR/scripts/ss-sens/ss-sens-mosquitto-tls.sh" "$HOST"
fi

# Initialise MQTT users if pwfile is missing
if [[ ! -f "$_DATA_DIR/coop/mosquitto/pwfile" ]]; then
  project_log "Initializing Mosquitto users"
  "$PROJECT_ROOT_DIR/scripts/ss-sens/ss-sens-mqtt-users.sh"
fi

# Start the stack
if [[ $# -eq 0 ]]; then
  exec "$PROJECT_ROOT_DIR/scripts/ss-sens/ss-sens-compose.sh" up -d
else
  exec "$PROJECT_ROOT_DIR/scripts/ss-sens/ss-sens-compose.sh" "$@"
fi
