"""Compose edge profile and CPU-only Dockerfile stay free of ML stacks."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
COMPOSE = PROJECT_ROOT / "docker" / "ss-sens" / "docker-compose.ss-sens.yml"
DOCKERFILE = PROJECT_ROOT / "docker" / "ss-sens" / "Dockerfile.ss-sens"

_EDGE_SERVICES = (
    "chirpstack-postgres:",
    "chirpstack-redis:",
    "chirpstack:",
    "chirpstack-gateway-bridge:",
    "chirpstack-rest-api:",
    "node-exporter:",
)

_ML_MARKERS = (
    "torch",
    "nvidia",
    "cuda",
    "transformers",
    "onnxruntime",
    "ctranslate2",
    "streamlit",
    "faster-whisper",
)


def _service_block(text: str, heading: str) -> str:
    start = text.find(f"\n  {heading}\n")
    if start < 0:
        start = text.find(f"\n  {heading}")
    assert start >= 0, f"missing service {heading}"
    rest = text[start + 1 :]
    lines = rest.splitlines()
    collected = [lines[0]]
    for line in lines[1:]:
        if line.startswith("  ") and not line.startswith("    ") and line.rstrip().endswith(":"):
            break
        collected.append(line)
    return "\n".join(collected)


def test_edge_profile_covers_pi_stack() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    assert "ss-sens:" in text
    assert "mosquitto:" in text
    for heading in _EDGE_SERVICES:
        block = _service_block(text, heading)
        assert "- edge" in block, f"{heading} missing edge profile"
        assert "cpus:" in block
        assert "memory:" in block


def test_metrics_profile_stays_on_prometheus_stack() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    for heading in ("prometheus:", "grafana:", "cadvisor:"):
        block = _service_block(text, heading)
        assert "- metrics" in block
        assert "- edge" not in block
    node = _service_block(text, "node-exporter:")
    assert "- metrics" in node
    assert "- edge" in node


def test_ss_sens_service_has_cpu_memory_limits() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    block = _service_block(text, "ss-sens:")
    assert "COOP_SS_SENS_CPUS" in block
    assert "COOP_SS_SENS_MEMORY" in block
    assert "Dockerfile.ss-sens" in block


def test_dockerfile_is_cpu_only_slim() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "python:3.11-slim" in text.lower()
    instructions = "\n".join(
        line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")
    ).lower()
    for marker in _ML_MARKERS:
        assert marker not in instructions, f"Dockerfile instruction mentions {marker}"
