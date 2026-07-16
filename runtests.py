#!/usr/bin/env python3
"""Compile and run the Epic v1 examples and end-to-end tests."""

import os, sys, subprocess, re, shlex

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EPICC = os.path.join(SCRIPT_DIR, "build", "epic-v1.exe")
EXAMPLES_DIR = os.path.join(SCRIPT_DIR, "examples")
E2E_PASS_DIR = os.path.join(SCRIPT_DIR, "tests", "e2e", "pass")
EXEC_TIMEOUT = 1  # seconds, prevent link.py bugs from hanging


def parse_annotations(source):
    """Extract test annotations from # comments."""
    exit_code = None
    stdout_lines = []
    argv = []
    clean_paths = []
    for line in source.split("\n"):
        line = line.strip()
        if m := re.match(r'#\s*EXIT:\s*(-?\d+)', line):
            exit_code = int(m.group(1))
        elif m := re.match(r'#\s*STDOUT:\s*(.*)', line):
            stdout_lines.append(m.group(1))
        elif m := re.match(r'#\s*ARGV:\s*(.*)$', line):
            argv = shlex.split(m.group(1) or "")
        elif m := re.match(r'#\s*CLEAN:\s*(.+)$', line):
            clean_paths.extend(shlex.split(m.group(1)))
    stdout = "\n".join(stdout_lines) if stdout_lines else None
    return exit_code, stdout, argv, clean_paths


def clean_test_paths(paths):
    """Delete declared test artifacts under the repo root."""
    root = os.path.abspath(SCRIPT_DIR)
    for rel in paths:
        if os.path.isabs(rel):
            raise RuntimeError(f"# CLEAN path must be relative: {rel}")
        path = os.path.abspath(os.path.join(SCRIPT_DIR, rel))
        if os.path.commonpath([root, path]) != root:
            raise RuntimeError(f"# CLEAN path escapes repo root: {rel}")
        if os.path.isdir(path):
            raise RuntimeError(f"# CLEAN refuses to delete directory: {rel}")
        if os.path.exists(path):
            os.remove(path)


def check_executable(exe_path, argv, exit_expected, stdout_expected):
    proc = subprocess.run(
        [exe_path, *argv],
        capture_output=True, cwd=SCRIPT_DIR, timeout=EXEC_TIMEOUT,
    )
    failures = []
    if exit_expected is not None and proc.returncode != exit_expected:
        failures.append(f"EXIT: expected {exit_expected}, got {proc.returncode}")
    if stdout_expected is not None:
        raw = proc.stdout or b''
        actual = raw.decode('ascii', errors='replace').strip()[:len(stdout_expected) + 100]
        if actual != stdout_expected.strip():
            failures.append(f"STDOUT: expected {stdout_expected!r}, got {actual!r}")
    return failures


def run_test(ep_file):
    """Compile and run a single .ep file, return (pass, detail)."""
    with open(ep_file, "r", encoding="utf-8") as f:
        source = f.read()
    exit_expected, stdout_expected, argv, clean_paths = parse_annotations(source)
    
    if exit_expected is None and stdout_expected is None:
        return True, "no annotations — skipped"

    try:
        clean_test_paths(clean_paths)
    except RuntimeError as e:
        return False, str(e)
    
    # Compile
    rel = os.path.relpath(ep_file, SCRIPT_DIR)
    result = subprocess.run(
        [EPICC, rel],
        capture_output=True, text=True, cwd=SCRIPT_DIR, timeout=30,
    )
    if result.returncode != 0:
        return False, f"compile failed:\n{result.stderr[:500]}"
    
    safe = rel.replace("/", "_").replace("\\", "_")
    exe_path = os.path.join(SCRIPT_DIR, "build", "epic", safe + ".exe")
    native_path = os.path.join(SCRIPT_DIR, "build", "epic", safe + ".native.exe")
    if not os.path.exists(exe_path):
        return False, f"no exe produced: {exe_path}"
    if not os.path.exists(native_path):
        return False, f"no native exe produced: {native_path}"

    failures = [f"old: {failure}" for failure in check_executable(
        exe_path, argv, exit_expected, stdout_expected,
    )]
    clean_test_paths(clean_paths)
    failures.extend(f"native: {failure}" for failure in check_executable(
        native_path, argv, exit_expected, stdout_expected,
    ))
    
    if failures:
        try:
            clean_test_paths(clean_paths)
        except RuntimeError as e:
            failures.append(str(e))
        return False, "; ".join(failures)
    try:
        clean_test_paths(clean_paths)
    except RuntimeError as e:
        return False, str(e)
    return True, "OK"


def run_all():
    cases = []
    for suite, directory in (("examples", EXAMPLES_DIR), ("e2e", E2E_PASS_DIR)):
        if not os.path.isdir(directory):
            continue
        for name in sorted(f for f in os.listdir(directory) if f.endswith(".ep")):
            cases.append((suite, name, os.path.join(directory, name)))
    if not cases:
        print("No .ep test cases found")
        return 0, 1, 0

    passed = 0
    failed = 0
    skipped = 0

    print(f"Running {len(cases)} tests...\n")
    for suite, ep_name, ep_path in cases:
        try:
            ok, detail = run_test(ep_path)
        except subprocess.TimeoutExpired:
            ok, detail = False, "TIMEOUT (compile >30s)"
        except Exception as e:
            ok, detail = False, f"exception: {e}"
        status = "PASS" if ok else "FAIL"
        if "skipped" in detail:
            status = "SKIP"
            skipped += 1
        elif ok:
            passed += 1
        else:
            failed += 1
        case_name = f"{suite}/{ep_name}"
        print(f"  {status:5}  {case_name:32s}  {detail}")

    print(f"\n{passed} passed, {failed} failed, {skipped} skipped")
    return passed, failed, skipped


def main():
    if not os.path.isfile(EPICC):
        print("Missing build/epic-v1.exe; run python build_epic_v1.py first", file=sys.stderr)
        return 1
    _, failed, _ = run_all()

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
