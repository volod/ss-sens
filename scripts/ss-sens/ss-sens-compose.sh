#!/usr/bin/env bash
# Run the ss-sens docker-compose stack with runtime `PUID`/`PGID`.
#
# Usage:
#   ./scripts/ss-sens/ss-sens-compose.sh up -d
#   APP_ENV=dev ./scripts/ss-sens/ss-sens-compose.sh up -d
#   APP_ENV=test ./scripts/ss-sens/ss-sens-compose.sh down

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../shared/common.sh"
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -eq 0 ]]; then
  cat <<'EOF'
Usage: ./scripts/ss-sens/ss-sens-compose.sh <docker-compose-args...>

Examples:
  ./scripts/ss-sens/ss-sens-compose.sh up -d
  ./scripts/ss-sens/ss-sens-compose.sh logs -f
  APP_ENV=test ./scripts/ss-sens/ss-sens-compose.sh down
EOF
  [[ $# -eq 0 ]] && exit 1 || exit 0
fi

[[ -f "$(project_env_file)" ]] || project_die ".data/.env not found. Run './scripts/ss-sens/ss-sens-env.sh' or './scripts/ss-sens/ss-sens-bootstrap.sh' first."
project_ss_sens_compose "$@"
