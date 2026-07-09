#!/usr/bin/env python3
"""Write the single-file MIR runtime helper bundle.

The self-hosted compiler reads runtime/mir/helpers.mir at compile time, so the
bundle is committed.  The Python helper builders remain the mechanical source
for builder-backed helpers; helper text that has no builder can be preserved
from an existing bundle or a temporary split .mir source while migrating.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_MIR_DIR = ROOT / "runtime" / "mir"
BUNDLE = RUNTIME_MIR_DIR / "helpers.mir"

sys.path.insert(0, str(ROOT / "bootstrap"))

from mir import MirProgram  # noqa: E402
from mir_parser import parse_mir_file  # noqa: E402
import mir_runtime_helpers as runtime  # noqa: E402


def _load_helpers_from_file(path: Path) -> dict[str, object]:
    parsed = parse_mir_file(path, validate_program=False)
    helpers: dict[str, object] = {}
    for fn in parsed.functions:
        if fn.name in helpers:
            raise RuntimeError(f"duplicate MIR helper in {path}: {fn.name}")
        helpers[fn.name] = fn
    return helpers


def _load_text_sources() -> dict[str, object]:
    helpers: dict[str, object] = {}
    if BUNDLE.exists():
        helpers.update(_load_helpers_from_file(BUNDLE))
    for path in sorted(RUNTIME_MIR_DIR.glob("*.mir")):
        if path == BUNDLE:
            continue
        for name, fn in _load_helpers_from_file(path).items():
            if name in helpers:
                raise RuntimeError(f"duplicate MIR helper across runtime sources: {name}")
            helpers[name] = fn
    return helpers


def build_bundle_text() -> str:
    text_sources = _load_text_sources()
    builder_program = MirProgram()
    functions = []
    for name in runtime.IMPLEMENTED_MIR_HELPERS:
        if name in runtime._HELPER_EMITTERS:
            functions.append(runtime._HELPER_EMITTERS[name](builder_program))
        elif name in text_sources:
            functions.append(text_sources[name])
        else:
            raise RuntimeError(f"no source for MIR runtime helper: {name}")
    return "\n\n".join(fn.text() for fn in functions) + "\n"


def main() -> int:
    RUNTIME_MIR_DIR.mkdir(parents=True, exist_ok=True)
    text = build_bundle_text()
    BUNDLE.write_text(text, encoding="utf-8", newline="\n")
    count = text.count("define ")
    print(f"wrote {BUNDLE.relative_to(ROOT)} ({count} helpers)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
