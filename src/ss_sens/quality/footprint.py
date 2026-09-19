"""Edge footprint gate: the ss-sens base install must stay free of ML stacks.

Run: ``python -m ss_sens.quality.footprint`` (or ``make footprint``).

Wraps ``ss_kit.quality.footprint`` with the ss-sens forbidden set and default
platforms. Resolves the base dependencies of ``pyproject.toml`` (no extras) with
``uv pip compile --python-platform`` and fails when a forbidden distribution
appears anywhere in the resolution, direct or transitive.
"""

import sys
from collections.abc import Sequence

from ss_kit.quality.footprint import main as _kit_main

PLATFORMS = ("aarch64-unknown-linux-gnu", "x86_64-unknown-linux-gnu")
# onnxruntime-gpu is the CUDA-host name for the same forbidden runtime.
FORBIDDEN = (
    "torch",
    "transformers",
    "onnxruntime",
    "onnxruntime-gpu",
    "ctranslate2",
    "streamlit",
)
PYTHON_VERSION = "3.11"


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ss-sens footprint gate with edge-tier defaults."""
    args = list(argv) if argv is not None else sys.argv[1:]
    if "--forbid" not in args:
        for name in FORBIDDEN:
            args.extend(["--forbid", name])
    if "--platform" not in args:
        for platform in PLATFORMS:
            args.extend(["--platform", platform])
    if "--python-version" not in args:
        args.extend(["--python-version", PYTHON_VERSION])
    return _kit_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
