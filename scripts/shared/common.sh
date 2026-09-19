#!/usr/bin/env bash
# Shared helpers for ss-sens shell scripts and Make. Source this file; do not execute it.

if [[ -n "${SS_SENS_SCRIPTS_COMMON_SOURCED:-}" ]]; then
  return 0
fi
readonly SS_SENS_SCRIPTS_COMMON_SOURCED=1

ssc_project_root() {
  (cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
}

PROJECT_ROOT="${PROJECT_ROOT:-$(ssc_project_root)}"
readonly PROJECT_SCRIPTS_DIR="$PROJECT_ROOT/scripts"
readonly PROJECT_ROOT_DIR="$PROJECT_ROOT"
readonly PROJECT_ENV_FILE="$PROJECT_ROOT_DIR/.data/.env"
readonly PROJECT_SS_SENS_COMPOSE_FILE="$PROJECT_ROOT_DIR/docker/ss-sens/docker-compose.ss-sens.yml"

project_root_dir() {
  printf '%s\n' "$PROJECT_ROOT_DIR"
}

project_env_file() {
  printf '%s\n' "$PROJECT_ENV_FILE"
}

project_ss_sens_compose_file() {
  printf '%s\n' "$PROJECT_SS_SENS_COMPOSE_FILE"
}

project_cd_root() {
  cd "$PROJECT_ROOT_DIR"
}

project_log() {
  printf '[scripts] %s\n' "$*"
}

project_warn() {
  printf '[scripts] WARN: %s\n' "$*" >&2
}

project_die() {
  printf '[scripts] ERROR: %s\n' "$*" >&2
  exit 1
}

project_have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

project_require_cmd() {
  project_have_cmd "$1" || project_die "Required command not found: $1"
}

project_load_env_optional() {
  if [[ -f "$PROJECT_ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$PROJECT_ENV_FILE"
    set +a
  fi
  local _local_env="$PROJECT_ROOT_DIR/.data/.env.local"
  if [[ -f "$_local_env" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$_local_env"
    set +a
  fi
}

project_load_env_required() {
  [[ -f "$PROJECT_ENV_FILE" ]] || project_die ".data/.env not found. Run './scripts/ss-sens/ss-sens-env.sh' first."
  project_load_env_optional
}

project_default_app_env() {
  printf '%s\n' "${APP_ENV:-prod}"
}

project_data_dir() {
  local data_dir="./.data"
  for _pdd_layer in \
      "$PROJECT_ROOT_DIR/.env" \
      "$PROJECT_ROOT_DIR/.data/.env" \
      "$PROJECT_ROOT_DIR/.data/.env.local"; do
    if [[ -f "$_pdd_layer" ]]; then
      set -a
      # shellcheck disable=SC1090
      source "$_pdd_layer"
      set +a
    fi
  done
  unset _pdd_layer
  data_dir="${DATA_DIR:-$data_dir}"
  if [[ "$data_dir" != /* ]]; then
    data_dir="$PROJECT_ROOT_DIR/${data_dir#./}"
  fi
  printf '%s\n' "$data_dir"
}

project_export_runtime_ids() {
  export PUID
  export PGID
  PUID="$(id -u)"
  PGID="$(id -g)"
}

project_ss_sens_compose() {
  project_export_runtime_ids
  exec docker compose \
    --project-directory "$PROJECT_ROOT_DIR" \
    --env-file "$PROJECT_ENV_FILE" \
    -f "$PROJECT_SS_SENS_COMPOSE_FILE" \
    "$@"
}

project_python_bin() {
  if [[ -x "$PROJECT_ROOT_DIR/.venv/bin/python" ]]; then
    printf '%s\n' "$PROJECT_ROOT_DIR/.venv/bin/python"
  elif project_have_cmd python3; then
    printf '%s\n' "python3"
  elif project_have_cmd python; then
    printf '%s\n' "python"
  else
    project_die "Python interpreter not found. Create .venv or install python3."
  fi
}

project_run_python_module() {
  local module="$1"
  shift
  local python_bin
  python_bin="$(project_python_bin)"
  PYTHONPATH="$PROJECT_ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" \
    "$python_bin" -m "$module" "$@"
}

ssc_path_device() {
  local path="$1"
  local parent
  while [ -n "$path" ] && [ ! -e "$path" ]; do
    parent="$(dirname "$path")"
    [ "$parent" = "$path" ] && break
    path="$parent"
  done
  [ -e "$path" ] || return 1
  stat -c '%d' "$path" 2>/dev/null || stat -f '%d' "$path" 2>/dev/null
}

ssc_export_uv_link_mode() {
  local mode="${UV_LINK_MODE:-}"
  if [ -n "$mode" ] && [ "${mode,,}" != "auto" ]; then
    export UV_LINK_MODE
    return 0
  fi
  unset UV_LINK_MODE
  local cache_device
  local root_device
  mkdir -p "$UV_CACHE_DIR"
  cache_device="$(ssc_path_device "$UV_CACHE_DIR")" || cache_device=""
  root_device="$(ssc_path_device "$PROJECT_ROOT/.venv")" || root_device=""
  if [ -n "$cache_device" ] && [ -n "$root_device" ] && [ "$cache_device" != "$root_device" ]; then
    export UV_LINK_MODE=copy
  fi
}

ssc_export_tool_caches() {
  export UV_CACHE_DIR="${UV_CACHE_DIR:-$DATA_DIR/uv-cache}"
  export RUFF_CACHE_DIR="${RUFF_CACHE_DIR:-$DATA_DIR/cache/ruff}"
}

ssc_load_env() {
  if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    # shellcheck source=/dev/null
    . "$PROJECT_ROOT/.env"
    set +a
  fi
  DATA_DIR="${DATA_DIR:-$PROJECT_ROOT/.data}"
  case "$DATA_DIR" in
    /*) ;;
    *) DATA_DIR="$PROJECT_ROOT/${DATA_DIR#./}" ;;
  esac
  export DATA_DIR
  ssc_export_tool_caches
  ssc_export_uv_link_mode
}
