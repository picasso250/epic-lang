#!/usr/bin/env python3
"""Compile all v0 regression cases into one executable, then run by selector."""

import argparse
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
EPICC = ROOT / "epic.py"
BUNDLE_SOURCE = ROOT / "build" / "tests" / "v0_bundle.ep"
MAIN_PATTERN = re.compile(r"^fun main(?=\s*\()", re.MULTILINE)
DECL_PATTERN = re.compile(r"^(?:fun|type)\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)
EMBED_PATTERN = re.compile(r'\bembed\("([^"]*)"\)')
EXEC_TIMEOUT = 2


def cases() -> list[tuple[str, Path]]:
    found = []
    for suite, directory in (
        ("examples", ROOT / "examples"),
        ("e2e", ROOT / "tests" / "e2e" / "pass"),
    ):
        found.extend((suite, path) for path in sorted(directory.glob("*.ep")))
    return found


def annotations(source: Path) -> dict:
    result = {"exit": None, "stdout": None, "argv": [], "clean": []}
    stdout_lines = []
    for line in source.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if match := re.match(r"#\s*EXIT:\s*(-?\d+)", stripped):
            result["exit"] = int(match.group(1))
        elif match := re.match(r"#\s*STDOUT:\s*(.*)", stripped):
            stdout_lines.append(match.group(1))
        elif match := re.match(r"#\s*ARGV:\s*(.*)", stripped):
            result["argv"] = shlex.split(match.group(1) or "")
        elif match := re.match(r"#\s*CLEAN:\s*(.+)", stripped):
            result["clean"].extend(shlex.split(match.group(1)))
    result["stdout"] = "\n".join(stdout_lines) if stdout_lines else None
    return result


def clean_paths(paths: list[str]) -> None:
    root = ROOT.resolve()
    for relative in paths:
        if os.path.isabs(relative):
            raise RuntimeError(f"# CLEAN path must be relative: {relative}")
        target = (root / relative).resolve()
        if root not in target.parents or target.is_dir():
            raise RuntimeError(f"# CLEAN refuses path: {relative}")
        if target.exists():
            target.unlink()


def rewrite_embeds(text: str, source: Path) -> str:
    def replace(match: re.Match) -> str:
        literal = match.group(1)
        if os.path.isabs(literal):
            return match.group(0)
        resolved = (source.parent / literal).resolve()
        relative = os.path.relpath(resolved, BUNDLE_SOURCE.parent).replace("\\", "/")
        return f'embed("{relative}")'

    return EMBED_PATTERN.sub(replace, text)


def case_symbol(source: Path) -> str:
    return f"__test_{source.stem}"


def write_bundle(all_cases: list[tuple[str, Path]]) -> None:
    declarations = {}
    parts = []
    for suite, source in all_cases:
        text = rewrite_embeds(source.read_text(encoding="utf-8"), source)
        for name in DECL_PATTERN.findall(text):
            if name == "main":
                continue
            previous = declarations.get(name)
            if previous is not None:
                raise RuntimeError(f"duplicate top-level name {name}: {previous} and {source}")
            declarations[name] = source
        rewritten, count = MAIN_PATTERN.subn(f"fun {case_symbol(source)}", text)
        if count != 1:
            raise RuntimeError(f"expected one main in {source}, found {count}")
        parts.append(f"# source: {suite}/{source.name}\n{rewritten.rstrip()}\n")

    dispatcher = [
        "fun main(): void {",
        "    if argv.len < 2 {",
        "        os.ExitProcess(126)",
        "    }",
        "    let case_name = argv.data[argv.len - 1]",
    ]
    for _, source in all_cases:
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


def compile_bundle(all_cases: list[tuple[str, Path]], linker: str) -> Path:
    write_bundle(all_cases)
    relative = BUNDLE_SOURCE.relative_to(ROOT)
    result = subprocess.run(
        [sys.executable, str(EPICC), str(relative), "--linker", linker],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"bundle compile failed:\n{result.stderr[-1000:]}")
    executable = ROOT / "build" / relative.with_suffix(".exe")
    if not executable.is_file():
        raise RuntimeError(f"bundle compiler produced no executable: {executable}")
    return executable


def run_case(source: Path, executable: Path) -> tuple[bool, str]:
    expected = annotations(source)
    if expected["exit"] is None and expected["stdout"] is None:
        return True, "no annotations — skipped"
    clean_paths(expected["clean"])
    process = subprocess.run(
        [str(executable), *expected["argv"], source.stem],
        cwd=ROOT,
        capture_output=True,
        timeout=EXEC_TIMEOUT,
    )
    failures = []
    if expected["exit"] is not None and process.returncode != expected["exit"]:
        failures.append(f"EXIT: expected {expected['exit']}, got {process.returncode}")
    if expected["stdout"] is not None:
        actual = (process.stdout or b"").decode("ascii", errors="replace").strip()
        if actual != expected["stdout"].strip():
            failures.append(f"STDOUT: expected {expected['stdout']!r}, got {actual!r}")
    clean_paths(expected["clean"])
    return (False, "; ".join(failures)) if failures else (True, "OK")


def main() -> int:
    parser = argparse.ArgumentParser(description="Epic v0 bundled test runner")
    parser.add_argument("--linker", choices=("lld", "py"), default="py")
    args = parser.parse_args()
    linker = "lld-link" if args.linker == "lld" else "py"
    all_cases = cases()
    try:
        executable = compile_bundle(all_cases, linker)
    except Exception as error:
        print(f"Bundle failed: {error}")
        return 1

    print(f"Running {len(all_cases)} tests via {executable.name} ({executable.stat().st_size} bytes)...\n")
    passed = failed = skipped = 0
    for suite, source in all_cases:
        try:
            ok, detail = run_case(source, executable)
        except subprocess.TimeoutExpired:
            ok, detail = False, "TIMEOUT"
        except Exception as error:
            ok, detail = False, f"exception: {error}"
        status = "PASS" if ok else "FAIL"
        if "skipped" in detail:
            status = "SKIP"
            skipped += 1
        elif ok:
            passed += 1
        else:
            failed += 1
        print(f"  {status:5}  {suite}/{source.name:28}  {detail}")
    print(f"\n{passed} passed, {failed} failed, {skipped} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
