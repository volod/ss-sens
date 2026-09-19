#!/usr/bin/env bash
# Build the CPU-only ss-sens image for linux/amd64 and linux/arm64.
# On CUDA hosts this still uses python:3.11-slim (no NVIDIA base, no ML extras).
#
# Usage:
#   ./scripts/ss-sens/ss-sens-image.sh              # multi-arch build, load, sizes, QEMU smoke
#   ./scripts/ss-sens/ss-sens-image.sh build        # buildx --platform linux/arm64,linux/amd64
#   ./scripts/ss-sens/ss-sens-image.sh load [amd64|arm64]
#   ./scripts/ss-sens/ss-sens-image.sh sizes
#   ./scripts/ss-sens/ss-sens-image.sh smoke-arm64

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../shared/common.sh"
project_cd_root
ssc_load_env

DOCKERFILE="$PROJECT_ROOT_DIR/docker/ss-sens/Dockerfile.ss-sens"
BUILDER_NAME="${SS_SENS_BUILDER:-ss-sens}"
IMAGE_REPO="${SS_SENS_IMAGE_REPO:-ss-sens}"
PLATFORMS="linux/arm64,linux/amd64"
SMOKE_NAME="${SS_SENS_SMOKE_NAME:-ss-sens-arm64-smoke}"
SMOKE_PORT="${SS_SENS_SMOKE_PORT:-18081}"
OUT_DIR="${DATA_DIR}/ss-sens/images"
OCI_TAR="$OUT_DIR/ss-sens-linux-arm64-amd64.oci.tar"
SIZES_FILE="$OUT_DIR/sizes.txt"
HOST_ARCH="$(uname -m)"

log() { printf '[ss-sens-image] %s\n' "$*"; }
die() { printf '[ss-sens-image] ERROR: %s\n' "$*" >&2; exit 1; }

arch_from_uname() {
  case "$HOST_ARCH" in
    x86_64|amd64) printf 'amd64\n' ;;
    aarch64|arm64) printf 'arm64\n' ;;
    *) die "unsupported host arch: $HOST_ARCH" ;;
  esac
}

usage() {
  sed -n '2,14p' "$0"
}

need_docker() {
  project_require_cmd docker
  docker info >/dev/null 2>&1 || die "Docker daemon is not reachable."
  docker buildx version >/dev/null 2>&1 || die "docker buildx is required."
}

ensure_binfmt_arm64() {
  if docker buildx inspect "$BUILDER_NAME" 2>/dev/null | grep -q 'linux/arm64'; then
    return 0
  fi
  if docker buildx inspect default 2>/dev/null | grep -q 'linux/arm64'; then
    return 0
  fi
  log "Installing qemu binfmt for linux/arm64 (privileged one-shot)."
  docker run --privileged --rm tonistiigi/binfmt --install arm64 >/dev/null
}

ensure_builder() {
  ensure_binfmt_arm64
  if docker buildx inspect "$BUILDER_NAME" >/dev/null 2>&1; then
    return 0
  fi
  log "Creating buildx builder ${BUILDER_NAME} (docker-container, CPU only)."
  docker buildx create \
    --name "$BUILDER_NAME" \
    --driver docker-container \
    --bootstrap >/dev/null
}

image_tag() {
  local arch="$1"
  printf '%s:local-%s\n' "$IMAGE_REPO" "$arch"
}

cmd_build() {
  mkdir -p "$OUT_DIR"
  ensure_builder
  log "buildx build --platform ${PLATFORMS} -> ${OCI_TAR}"
  rm -f "$OCI_TAR"
  docker buildx build \
    --builder "$BUILDER_NAME" \
    --platform "$PLATFORMS" \
    --file "$DOCKERFILE" \
    --tag "${IMAGE_REPO}:local" \
    --output "type=oci,dest=${OCI_TAR}" \
    "$PROJECT_ROOT_DIR"
  log "Wrote ${OCI_TAR} ($(wc -c < "$OCI_TAR") bytes)"
}

cmd_load() {
  local arch="${1:-$(arch_from_uname)}"
  [[ "$arch" == "amd64" || "$arch" == "arm64" ]] || die "load arch must be amd64 or arm64"
  ensure_builder
  local tag
  tag="$(image_tag "$arch")"
  log "buildx build --platform linux/${arch} --load ${tag}"
  docker buildx build \
    --builder "$BUILDER_NAME" \
    --platform "linux/${arch}" \
    --file "$DOCKERFILE" \
    --tag "$tag" \
    --load \
    "$PROJECT_ROOT_DIR"
  if [[ "$arch" == "$(arch_from_uname)" ]]; then
    docker tag "$tag" "${IMAGE_REPO}:local"
    log "Tagged native ${IMAGE_REPO}:local -> ${tag}"
  fi
}

cmd_sizes() {
  mkdir -p "$OUT_DIR"
  local host
  host="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  {
    printf 'recorded_at: %s\n' "$host"
    printf 'host_arch:   %s\n' "$HOST_ARCH"
    printf 'note:        CPU-only python:3.11-slim; no NVIDIA/CUDA layers\n'
    printf 'size:        docker image inspect .Size (all layers)\n'
    printf '\n'
    for arch in amd64 arm64; do
      local tag
      tag="$(image_tag "$arch")"
      if docker image inspect "$tag" >/dev/null 2>&1; then
        python3 - "$tag" <<'PY'
import json, subprocess, sys
tag = sys.argv[1]
data = json.loads(subprocess.check_output(["docker", "image", "inspect", tag], text=True))[0]
size = int(data["Size"])
print(
    "%s  %s/%s  %s bytes  %.1f MiB"
    % (tag, data["Os"], data["Architecture"], size, size / 1024 / 1024)
)
PY
      else
        printf '%s  not-loaded\n' "$tag"
      fi
    done
    if [[ -f "$OCI_TAR" ]]; then
      python3 - "$OCI_TAR" <<'PY'
import pathlib, sys
path = pathlib.Path(sys.argv[1])
size = path.stat().st_size
print("\noci_archive: %s  %s bytes  %.1f MiB" % (path, size, size / 1024 / 1024))
PY
    fi
  } | tee "$SIZES_FILE"
  log "Wrote ${SIZES_FILE}"
}

wait_http() {
  local url="$1"
  local tries="${2:-40}"
  local i
  for i in $(seq 1 "$tries"); do
    if python3 -c "import urllib.request; urllib.request.urlopen('${url}', timeout=2)" \
      >/dev/null 2>&1; then
      return 0
    fi
    sleep 3
  done
  return 1
}

cmd_smoke_arm64() {
  local tag
  tag="$(image_tag arm64)"
  docker image inspect "$tag" >/dev/null 2>&1 || die "missing ${tag}; run: $0 load arm64"
  docker rm -f "$SMOKE_NAME" >/dev/null 2>&1 || true
  log "Starting ${tag} under QEMU on 127.0.0.1:${SMOKE_PORT}"
  docker run -d --rm \
    --name "$SMOKE_NAME" \
    --platform linux/arm64 \
    --publish "127.0.0.1:${SMOKE_PORT}:8081" \
    --env COOP_HTTP_HOST=0.0.0.0 \
    --env COOP_HTTP_PORT=8081 \
    --env COOP_MQTT_HOST=127.0.0.1 \
    "$tag" >/dev/null
  cleanup() { docker rm -f "$SMOKE_NAME" >/dev/null 2>&1 || true; }
  trap cleanup EXIT
  local base="http://127.0.0.1:${SMOKE_PORT}"
  wait_http "${base}/health" 40 || {
    docker logs "$SMOKE_NAME" >&2 || true
    die "arm64 smoke: /health did not answer"
  }
  local sensors
  sensors="$(python3 -c "import urllib.request; print(urllib.request.urlopen('${base}/site/sensors', timeout=5).read().decode())")"
  printf '%s\n' "$sensors" | grep -q '"sensors"' \
    || die "arm64 smoke: /site/sensors body was not a site state: ${sensors}"
  log "arm64 QEMU /site/sensors ok: ${sensors}"
  cleanup
  trap - EXIT
}

cmd_all() {
  cmd_build
  cmd_load amd64
  cmd_load arm64
  cmd_sizes
  cmd_smoke_arm64
}

need_docker
cmd="${1:-all}"
case "$cmd" in
  -h|--help) usage; exit 0 ;;
  all) cmd_all ;;
  build) cmd_build ;;
  load) cmd_load "${2:-}" ;;
  sizes) cmd_sizes ;;
  smoke-arm64) cmd_smoke_arm64 ;;
  *) die "unknown command: $cmd (try --help)" ;;
esac
