#!/usr/bin/env python3
"""
Build link.ep, relink every current example .obj with it, then run the outputs
against the same # EXIT / # STDOUT annotations used by runtests.py.
"""

import os
import re
import shlex
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PREVIOUS_EPIC = os.environ.get(
    "PREVIOUS_EPIC",
    os.path.join(SCRIPT_DIR, "build", "v0.exe"),
)
CURRENT_EPIC = os.path.join(SCRIPT_DIR, "build", "epic", "epic.ep.exe")
LINK_EP_EXE = os.path.join(SCRIPT_DIR, "build", "epic", "link.ep.exe")
EXAMPLES_DIR = os.path.join(SCRIPT_DIR, "examples")
SOURCES = ["epic.ep", "codegen_support.ep", "codegen.ep", "parser.ep", "lexer.ep"]


def run_checked(cmd, label, timeout=60):
    result = subprocess.run(
        cmd,
        cwd=SCRIPT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"{label} failed with exit {result.returncode}\n"
            + result.stdout[-2000:]
            + result.stderr[-2000:]
        )
    return result


def parse_annotations(source):
    exit_code = None
    stdout_lines = []
    argv = []
    for line in source.splitlines():
        line = line.strip()
        if m := re.match(r"#\s*EXIT:\s*(-?\d+)", line):
            exit_code = int(m.group(1))
        elif m := re.match(r"#\s*STDOUT:\s*(.*)", line):
            stdout_lines.append(m.group(1))
        elif m := re.match(r"#\s*ARGV:\s*(.*)$", line):
            argv = shlex.split(m.group(1) or "")
    stdout = "\n".join(stdout_lines) if stdout_lines else None
    return exit_code, stdout, argv


def example_obj_path(ep_name):
    rel = f"examples/{ep_name}"
    return os.path.join(SCRIPT_DIR, "build", "epic", rel.replace("/", "_") + ".obj")


def ensure_tools_and_objects():
    if not os.path.exists(PREVIOUS_EPIC):
        raise RuntimeError("previous Epic compiler not found; run the v0 bootstrap first")
    run_checked([PREVIOUS_EPIC, *SOURCES], "previous Epic -> current Epic")
    run_checked([CURRENT_EPIC, "link.ep"], "current Epic -> link.ep")

    # runtests.py also builds each example .obj with the current compiler.
    run_checked([sys.executable, "runtests.py"], "example object build", timeout=120)


def main():
    ensure_tools_and_objects()
    examples = sorted(f for f in os.listdir(EXAMPLES_DIR) if f.endswith(".ep"))
    passed = 0
    failed = 0
    skipped = 0

    for ep_name in examples:
        source = open(os.path.join(EXAMPLES_DIR, ep_name), encoding="utf-8").read()
        exit_expected, stdout_expected, argv = parse_annotations(source)
        if exit_expected is None and stdout_expected is None:
            skipped += 1
            continue

        obj_path = example_obj_path(ep_name)
        exe_path = os.path.join(SCRIPT_DIR, "build", "epic", f"link_ep_{ep_name}.exe")
        if not os.path.exists(obj_path):
            print(f"FAIL   {ep_name:24s} missing object: {obj_path}")
            failed += 1
            continue

        try:
            run_checked([LINK_EP_EXE, obj_path, "-o", exe_path], "link.ep", timeout=10)
            proc = subprocess.run(
                [exe_path, *argv],
                cwd=SCRIPT_DIR,
                capture_output=True,
                timeout=1,
            )
        except Exception as e:
            print(f"FAIL   {ep_name:24s} {e}")
            failed += 1
            continue

        failures = []
        if exit_expected is not None and proc.returncode != exit_expected:
            failures.append(f"EXIT expected {exit_expected}, got {proc.returncode}")
        if stdout_expected is not None:
            actual = (proc.stdout or b"").decode("ascii", errors="replace").strip()
            actual = actual[: len(stdout_expected) + 100]
            if actual != stdout_expected.strip():
                failures.append(f"STDOUT expected {stdout_expected!r}, got {actual!r}")

        if failures:
            print(f"FAIL   {ep_name:24s} {'; '.join(failures)}")
            failed += 1
        else:
            print(f"PASS   {ep_name:24s} OK")
            passed += 1

    print(f"\n{passed} passed, {failed} failed, {skipped} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
