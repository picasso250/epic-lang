#!/usr/bin/env python3
"""
Example test runner for Epic examples.

Scans examples/*.ep, reads # EXIT / # STDOUT annotations, compiles with either
Python reference compiler mode or the self-hosted Epic compiler, runs outputs,
and reports pass/fail.
"""

import argparse
import os
import subprocess
import sys

from compiler_sources import SELF_HOST_COMPILER_SOURCES

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.join(SCRIPT_DIR, "tests")
sys.path.insert(0, TESTS_DIR)

import ep_runner

EXAMPLES_DIR = os.path.join(SCRIPT_DIR, "examples")
SELF_HOST_BUILD_DIR = os.path.join(SCRIPT_DIR, "build", "self_hosted_examples")
SELF_HOST_COMPILER_DIR = os.path.join(SCRIPT_DIR, "build", "self_hosted_compiler")
SELF_HOST_COMPILER_EXE = os.path.join(SELF_HOST_COMPILER_DIR, "src", "epic.exe")


def compile_self_hosted_compiler():
    """Build the Epic compiler using the Python stage-0 compiler."""
    os.makedirs(SELF_HOST_COMPILER_DIR, exist_ok=True)
    cmd = [
        sys.executable,
        ep_runner.EPICC,
        "--main",
        "src/epic.ep",
        *SELF_HOST_COMPILER_SOURCES,
        "--out-dir",
        SELF_HOST_COMPILER_DIR,
        "--linker",
        "py",
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=SCRIPT_DIR,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError("self-hosted compiler build failed:\n" + (result.stdout + result.stderr)[-2000:])
    if not os.path.exists(SELF_HOST_COMPILER_EXE):
        raise RuntimeError(f"self-hosted compiler missing: {SELF_HOST_COMPILER_EXE}")
    return SELF_HOST_COMPILER_EXE


def self_hosted_output_path(ep_file):
    rel = os.path.relpath(ep_file, SCRIPT_DIR)
    stem = os.path.splitext(rel)[0]
    return os.path.join(SELF_HOST_BUILD_DIR, stem + ".exe")


def run_test_self_hosted(ep_file, compiler_exe):
    """Compile and run one .ep file using an already-built Epic compiler."""
    annotations = ep_runner.read_annotations(ep_file)
    if not ep_runner.has_expectations(annotations):
        return True, "no annotations — skipped"
    if annotations["compile_fail"] is not None:
        return True, "compile-fail case skipped for self-hosted examples"

    try:
        ep_runner.clean_test_paths(annotations["clean_paths"], root_dir=SCRIPT_DIR)
    except RuntimeError as e:
        return False, str(e)

    exe_path = self_hosted_output_path(ep_file)
    os.makedirs(os.path.dirname(exe_path), exist_ok=True)
    obj_path = exe_path + ".obj"
    for out in (obj_path, exe_path):
        if os.path.exists(out):
            os.remove(out)

    ep_rel = os.path.relpath(ep_file, SCRIPT_DIR).replace(os.sep, "/")
    exe_rel = os.path.relpath(exe_path, SCRIPT_DIR).replace(os.sep, "/")
    cmd = [
        compiler_exe,
        ep_rel,
        "--main",
        ep_rel,
        "-o",
        exe_rel,
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=SCRIPT_DIR,
        timeout=30,
    )
    if result.returncode != 0:
        return False, "self-hosted compile failed:\n" + (result.stdout + result.stderr)[-1000:]
    if "timing:" in result.stdout or "stats:" in result.stdout:
        return False, "self-hosted compiler printed verbose diagnostics without --verbose"
    if annotations["compile_only"]:
        return True, "compile only"
    if not os.path.exists(exe_path):
        return False, f"no exe produced: {exe_path}"

    proc = subprocess.run(
        [exe_path, *annotations["argv"]],
        capture_output=True,
        cwd=SCRIPT_DIR,
        timeout=ep_runner.EXEC_TIMEOUT,
    )
    failures = ep_runner.check_runtime_result(proc, annotations)
    try:
        ep_runner.clean_test_paths(annotations["clean_paths"], root_dir=SCRIPT_DIR)
    except RuntimeError as e:
        failures.append(str(e))
    if failures:
        return False, "; ".join(failures)
    return True, "OK"


def run_test(ep_file, linker="py"):
    return ep_runner.run_python_case(ep_file, linker=linker, root_dir=SCRIPT_DIR)


def resolve_example(arg):
    if arg is None:
        return None

    if arg.endswith(".ep") or os.sep in arg or "/" in arg:
        path = os.path.abspath(os.path.join(SCRIPT_DIR, arg))
    else:
        path = os.path.abspath(os.path.join(EXAMPLES_DIR, arg + ".ep"))

    root = os.path.abspath(SCRIPT_DIR)
    if os.path.commonpath([root, path]) != root:
        raise RuntimeError(f"example path escapes repo root: {arg}")
    if not path.endswith(".ep"):
        raise RuntimeError(f"example must be a .ep file: {arg}")
    if not os.path.exists(path):
        rel = os.path.relpath(path, SCRIPT_DIR)
        raise RuntimeError(f"example not found: {rel}")
    return path


def run_case(ep_path, linker, self_hosted=False, compiler_exe=None):
    if self_hosted:
        return run_test_self_hosted(ep_path, compiler_exe)
    return run_test(ep_path, linker=linker)


def run_all(linker, self_hosted=False, compiler_exe=None):
    examples = sorted(f for f in os.listdir(EXAMPLES_DIR) if f.endswith(".ep"))
    if not examples:
        print("No .ep files found in examples/")
        return 0, 1, 0

    passed = failed = skipped = 0
    mode = "self-hosted" if self_hosted else "python-reference"
    print(f"Running {len(examples)} examples ({mode})...\n")
    for ep_name in examples:
        ep_path = os.path.join(EXAMPLES_DIR, ep_name)
        try:
            ok, detail = run_case(ep_path, linker, self_hosted=self_hosted, compiler_exe=compiler_exe)
        except subprocess.TimeoutExpired:
            ok, detail = False, "TIMEOUT"
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
        print(f"  {status:5}  {ep_name:24s}  {detail}")

    print(f"\n{passed} passed, {failed} failed, {skipped} skipped")
    return passed, failed, skipped


def main():
    parser = argparse.ArgumentParser(description="Epic example test runner")
    parser.add_argument("example", nargs="?", help="exact example name or .ep path")
    parser.add_argument("--linker", choices=["lld", "py"], default="py",
                        help="Which linker to use with the Python reference compiler (default: py)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--py-only", action="store_true",
                      help="Run examples with the Python reference compiler only (default)")
    mode.add_argument("--self-hosted", action="store_true",
                      help="Build src/epic.ep with Python, then use that Epic compiler for examples")
    args = parser.parse_args()

    ep_path = resolve_example(args.example)
    linker_val = "lld-link" if args.linker == "lld" else "py"

    compiler_exe = compile_self_hosted_compiler() if args.self_hosted else None
    if ep_path is not None:
        try:
            ok, detail = run_case(ep_path, linker_val, self_hosted=args.self_hosted, compiler_exe=compiler_exe)
        except subprocess.TimeoutExpired:
            ok, detail = False, "TIMEOUT"
        except Exception as e:
            ok, detail = False, f"exception: {e}"
        status = "SKIP" if "skipped" in detail else ("PASS" if ok else "FAIL")
        name = os.path.relpath(ep_path, EXAMPLES_DIR)
        print(f"  {status:5}  {name:24s}  {detail}")
        sys.exit(0 if ok else 1)

    _, failed, _ = run_all(linker_val, self_hosted=args.self_hosted, compiler_exe=compiler_exe)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
