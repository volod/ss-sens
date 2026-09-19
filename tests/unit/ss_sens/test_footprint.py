"""ss-sens edge footprint: aarch64 base install excludes ML stacks."""

import os
import shutil
from pathlib import Path

import pytest

from ss_kit.quality.footprint import Resolution, findings, parse_pins
from ss_sens.quality.footprint import FORBIDDEN, PLATFORMS, main

PROJECT_ROOT = Path(__file__).resolve().parents[3]
network = pytest.mark.skipif(
    os.environ.get("SS_OFFLINE") == "1" or shutil.which("uv") is None,
    reason="resolves from the package index (SS_OFFLINE=1 or no uv)",
)


def test_forbidden_set_matches_the_specification() -> None:
    assert set(FORBIDDEN) >= {
        "torch",
        "transformers",
        "onnxruntime",
        "ctranslate2",
        "streamlit",
    }
    assert "aarch64-unknown-linux-gnu" in PLATFORMS


def test_findings_flag_planted_torch() -> None:
    heavy = Resolution(
        "aarch64-unknown-linux-gnu",
        parse_pins("torch==2.9.1+cpu\npydantic==2.13.5\n"),
        "",
    )
    light = Resolution("aarch64-unknown-linux-gnu", {"pydantic": "2.13.5"}, "")
    assert findings([heavy], FORBIDDEN) == [
        "aarch64-unknown-linux-gnu: base install resolves forbidden torch==2.9.1+cpu"
    ]
    assert findings([light], FORBIDDEN) == []


def _planted(tmp_path: Path, dependency: str) -> Path:
    text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    anchor = 'dependencies = [\n    "aiomqtt>=2.3",'
    assert anchor in text
    planted = tmp_path / "pyproject.toml"
    planted.write_text(
        text.replace(anchor, f'dependencies = [\n    "{dependency}",\n    "aiomqtt>=2.3",'),
        encoding="utf-8",
    )
    return planted


@network
def test_repository_base_install_is_light(tmp_path: Path) -> None:
    out = tmp_path / "footprint"
    assert main(["--pyproject", str(PROJECT_ROOT / "pyproject.toml"), "--out", str(out)]) == 0
    aarch64 = (out / "base-aarch64-unknown-linux-gnu.txt").read_text(encoding="utf-8")
    assert "ss-common @" in aarch64
    assert "pydantic==" in aarch64
    resolved = parse_pins(aarch64)
    for name in FORBIDDEN:
        assert name not in resolved


@network
def test_planted_torch_dependency_fails_the_gate(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert main(["--pyproject", str(_planted(tmp_path, "torch"))]) == 1
    assert "aarch64-unknown-linux-gnu: base install resolves forbidden torch==" in caplog.text
