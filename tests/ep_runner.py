#!/usr/bin/env python3
"""Shared Epic .ep test-case runner utilities."""

import os
import re
import shlex
import subprocess
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EPICC = os.path.join(ROOT_DIR, "bootstrap", "epic.py")
EXEC_TIMEOUT = 1  # seconds, prevent linker/runtime bugs from hanging tests


def parse_annotations(source):
    """Extract test annotations from # comments."""
    annotations = {
        "exit_code": None,
        "stdout": None,
        "stdout_contains": [],
        "argv": [],
        "clean_paths": [],
        "compile_fail": None,
        "compile_only": False,
    }
    stdout_lines = []
    for line in source.split("\n"):
        line = line.strip()
        if m := re.match(r'#\s*EXIT:\s*(-?\d+)', line):
            annotations["exit_code"] = int(m.group(1))
        elif m := re.match(r'#\s*STDOUT:\s*(.*)', line):
            stdout_lines.append(m.group(1))
        elif m := re.match(r'#\s*STDOUT_CONTAINS:\s*(.*)', line):
            annotations["stdout_contains"].append(m.group(1))
        elif m := re.match(r'#\s*ARGV:\s*(.*)$', line):
            annotations["argv"] = shlex.split(m.group(1) or "")
        elif m := re.match(r'#\s*CLEAN:\s*(.+)$', line):
            annotations["clean_paths"].extend(shlex.split(m.group(1)))
        elif m := re.match(r'#\s*COMPILE_FAIL:\s*(.*)$', line):
            annotations["compile_fail"] = m.group(1).strip() or ""
        elif re.match(r'#\s*COMPILE_ONLY\b', line):
            annotations["compile_only"] = True
    annotations["stdout"] = "\n".join(stdout_lines) if stdout_lines else None
    return annotations


def read_annotations(ep_file):
    with open(ep_file, "r", encoding="utf-8") as f:
        return parse_annotations(f.read())


def has_expectations(annotations):
    return any([
        annotations["exit_code"] is not None,
        annotations["stdout"] is not None,
        bool(annotations["stdout_contains"]),
        annotations["compile_fail"] is not None,
        annotations["compile_only"],
    ])


def clean_test_paths(paths, root_dir=ROOT_DIR):
    """Delete declared test artifacts under the repo root."""
    root = os.path.abspath(root_dir)
    for rel in paths:
        if os.path.isabs(rel):
            raise RuntimeError(f"# CLEAN path must be relative: {rel}")
        path = os.path.abspath(os.path.join(root, rel))
        if os.path.commonpath([root, path]) != root:
            raise RuntimeError(f"# CLEAN path escapes repo root: {rel}")
        if os.path.isdir(path):
            raise RuntimeError(f"# CLEAN refuses to delete directory: {rel}")
        if os.path.exists(path):
            os.remove(path)


def check_runtime_result(proc, annotations):
    failures = []
    expected_exit = annotations["exit_code"]
    expected_stdout = annotations["stdout"]
    stdout_contains = annotations["stdout_contains"]

    if expected_exit is not None and proc.returncode != expected_exit:
        failures.append(f"EXIT: expected {expected_exit}, got {proc.returncode}")

    actual_stdout = (proc.stdout or b"").decode("ascii", errors="replace")
    if expected_stdout is not None:
        actual = actual_stdout.strip()[:len(expected_stdout) + 100]
        if actual != expected_stdout.strip():
            failures.append(f"STDOUT: expected {expected_stdout!r}, got {actual!r}")
    for needle in stdout_contains:
        if needle not in actual_stdout:
            failures.append(f"STDOUT_CONTAINS: expected {needle!r} in {actual_stdout[:500]!r}")

    return failures


def compiled_exe_path(ep_file, root_dir=ROOT_DIR):
    rel = os.path.relpath(ep_file, root_dir)
    return os.path.join(root_dir, "build", os.path.splitext(rel)[0] + ".exe")


def run_python_case(ep_file, linker="py", root_dir=ROOT_DIR, epicc=EPICC):
    """Compile and run a single .ep file with the Python reference compiler."""
    annotations = read_annotations(ep_file)
    if not has_expectations(annotations):
        return True, "no annotations — skipped"

    try:
        clean_test_paths(annotations["clean_paths"], root_dir=root_dir)
    except RuntimeError as e:
        return False, str(e)

    result = subprocess.run(
        [sys.executable, epicc, ep_file, "--linker", linker],
        capture_output=True,
        text=True,
        cwd=root_dir,
        timeout=30,
    )

    expected_compile_fail = annotations["compile_fail"]
    if expected_compile_fail is not None:
        output = result.stdout + result.stderr
        if result.returncode == 0:
            return False, "compile succeeded, expected failure"
        if expected_compile_fail and expected_compile_fail not in output:
            return False, f"compile failed, but expected {expected_compile_fail!r} in:\n{output[:500]}"
        return True, "compile failed as expected"

    if result.returncode != 0:
        return False, f"compile failed:\n{result.stderr[:500]}"
    if annotations["compile_only"]:
        return True, "compile only"

    exe_path = compiled_exe_path(ep_file, root_dir=root_dir)
    if not os.path.exists(exe_path):
        return False, f"no exe produced: {exe_path}"

    proc = subprocess.run(
        [exe_path, *annotations["argv"]],
        capture_output=True,
        cwd=root_dir,
        timeout=EXEC_TIMEOUT,
    )
    failures = check_runtime_result(proc, annotations)

    try:
        clean_test_paths(annotations["clean_paths"], root_dir=root_dir)
    except RuntimeError as e:
        failures.append(str(e))

    if failures:
        return False, "; ".join(failures)
    return True, "OK"
