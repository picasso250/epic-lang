#!/usr/bin/env python3
"""Compile the Epic end-to-end tests once, then run each case in isolation."""

import re
import subprocess
import sys
from pathlib import Path


TESTS = Path(__file__).resolve().parents[1]
ROOT = TESTS.parent
sys.path.insert(0, str(TESTS))
import ep_runner

BUNDLE_SOURCE = ROOT / "build" / "tests" / "e2e_bundle.ep"
MAIN_PATTERN = re.compile(r"^fun main(?=\s*\()", re.MULTILINE)
DECL_PATTERN = re.compile(r"^(?:fun|type)\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)
COMPILE_ERROR_PATTERN = re.compile(r"^#\s*COMPILE_ERROR:\s*(.+)$", re.MULTILINE)


def case_symbol(source: Path) -> str:
    return f"__e2e_case_{source.stem}"


def write_bundle(cases: list[Path]) -> None:
    declarations = {}
    parts = []
    for source in cases:
        text = source.read_text(encoding="utf-8")
        for name in DECL_PATTERN.findall(text):
            if name == "main":
                continue
            previous = declarations.get(name)
            if previous is not None:
                raise RuntimeError(
                    f"duplicate top-level name {name}: {previous.name} and {source.name}"
                )
            declarations[name] = source
        rewritten, count = MAIN_PATTERN.subn(f"fun {case_symbol(source)}", text)
        if count != 1:
            raise RuntimeError(f"expected exactly one main function in {source.name}, found {count}")
        parts.append(f"# source: {source.as_posix()}\n{rewritten.rstrip()}\n")

    dispatcher = [
        "fun main(): void {",
        "    if argv.len < 2 {",
        "        os.ExitProcess(126)",
        "    }",
        "    let case_name = argv.data[argv.len - 1]",
        "    argv.len = argv.len - 1",
    ]
    for source in cases:
        dispatcher.extend(
            (
                f'    if case_name == "{source.stem}" {{',
                f"        {case_symbol(source)}()",
                "        os.ExitProcess(0)",
                "    }",
            )
        )
    dispatcher.extend(("    os.ExitProcess(127)", "}"))
    parts.append("\n".join(dispatcher) + "\n")

    BUNDLE_SOURCE.parent.mkdir(parents=True, exist_ok=True)
    BUNDLE_SOURCE.write_text("\n".join(parts), encoding="utf-8")


def compile_bundle(cases: list[Path]) -> Path:
    write_bundle(cases)
    relative = BUNDLE_SOURCE.relative_to(ROOT)
    executable = ep_runner.output_path(BUNDLE_SOURCE)
    executable.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [str(ep_runner.compiler_path()), "-o", str(executable), str(relative)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"bundle compile failed:\n{result.stderr[:1000]}")
    if not executable.is_file():
        raise RuntimeError(f"bundle compiler produced no executable: {executable}")
    return executable


def run_compile_failure(source: Path) -> tuple[bool, str]:
    text = source.read_text(encoding="utf-8")
    match = COMPILE_ERROR_PATTERN.search(text)
    if match is None:
        return False, "missing # COMPILE_ERROR annotation"
    relative = source.relative_to(ROOT)
    executable = ep_runner.output_path(source)
    executable.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [str(ep_runner.compiler_path()), "-o", str(executable), str(relative)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=30,
    )
    if result.returncode == 0:
        return False, "compilation unexpectedly succeeded"
    expected = match.group(1).strip()
    output = result.stdout + result.stderr
    if expected not in output:
        return False, f"expected {expected!r}, got {output[:500]!r}"
    return True, "OK"


def main() -> int:
    cases = sorted((Path(__file__).parent / "pass").glob("*.ep"))
    failures = sorted((Path(__file__).parent / "fail").glob("*.ep"))
    try:
        executable = compile_bundle(cases)
    except Exception as error:
        print(f"E2E bundle failed: {error}")
        return 1

    failed = 0
    print(f"Running {len(cases)} end-to-end tests via {executable.name} ({executable.stat().st_size} bytes)...\n")
    for source in cases:
        try:
            ok, detail = ep_runner.run_compiled_case(
                source,
                executable,
                (source.stem,),
            )
        except subprocess.TimeoutExpired:
            ok, detail = False, "TIMEOUT"
        except Exception as error:
            ok, detail = False, f"exception: {error}"
        print(f"  {'PASS' if ok else 'FAIL':5}  {source.name:32}  {detail}")
        failed += not ok
    for source in failures:
        ok, detail = run_compile_failure(source)
        print(f"  {'PASS' if ok else 'FAIL':5}  {source.name:32}  {detail}")
        failed += not ok
    total = len(cases) + len(failures)
    print(f"\n{total - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
