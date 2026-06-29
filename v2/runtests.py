#!/usr/bin/env python3
"""
Epic v2 test runner.
Scans examples/*.ep, reads # EXIT: and # STDOUT: annotations,
builds the current Epic compiler with the v1 bootstrap anchor, then compiles,
runs, and reports pass/fail.
"""

import os, sys, subprocess, re, shlex

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCES = ["epic.ep", "codegen_support.ep", "codegen.ep", "parser.ep", "lexer.ep"]
DEFAULT_PREVIOUS_EPIC = os.path.join(SCRIPT_DIR, "build", "v1.exe")
PREVIOUS_EPIC = os.environ.get("PREVIOUS_EPIC", DEFAULT_PREVIOUS_EPIC)
CURRENT_EPIC = os.path.join(SCRIPT_DIR, "build", "epic", "epic.ep.exe")
LINK_EXE = os.path.join(SCRIPT_DIR, "build", "link.exe")
LEGACY_LINK_EP_EXE = os.path.join(SCRIPT_DIR, "build", "epic", "link.ep.exe")
EXAMPLES_DIR = os.path.join(SCRIPT_DIR, "examples")
EXEC_TIMEOUT = 1


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


def run_checked(cmd, label, timeout=30):
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=SCRIPT_DIR,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"{label} failed with exit {result.returncode}\n"
            + result.stdout[-2000:]
            + result.stderr[-2000:]
        )
    return result


def ensure_current_compiler():
    if not os.path.exists(PREVIOUS_EPIC):
        raise RuntimeError(
            "previous Epic compiler not found. Set PREVIOUS_EPIC or build "
            + os.path.relpath(DEFAULT_PREVIOUS_EPIC, SCRIPT_DIR)
        )
    if not os.path.exists(LINK_EXE):
        raise RuntimeError(
            "Epic linker not found. Run python ..\\epic-bootstrap.py to build "
            + os.path.relpath(LINK_EXE, SCRIPT_DIR)
        )
    os.makedirs(os.path.dirname(LEGACY_LINK_EP_EXE), exist_ok=True)
    if not os.path.exists(LEGACY_LINK_EP_EXE):
        import shutil

        shutil.copy2(LINK_EXE, LEGACY_LINK_EP_EXE)
    run_checked([PREVIOUS_EPIC, *SOURCES], "previous Epic -> current Epic", timeout=60)
    if not os.path.exists(CURRENT_EPIC):
        raise RuntimeError(f"expected compiler output missing: {CURRENT_EPIC}")


def epic_output_exe(ep_file):
    rel = os.path.relpath(ep_file, SCRIPT_DIR).replace("\\", "/")
    return os.path.join(SCRIPT_DIR, "build", "epic", rel.replace("/", "_") + ".exe")


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
    
    try:
        run_checked([CURRENT_EPIC, os.path.relpath(ep_file, SCRIPT_DIR)], "compile")
    except RuntimeError as e:
        return False, str(e)

    exe_path = epic_output_exe(ep_file)
    if not os.path.exists(exe_path):
        return False, f"no exe produced: {exe_path}"

    proc = subprocess.run(
        [exe_path, *argv],
        capture_output=True, cwd=SCRIPT_DIR, timeout=EXEC_TIMEOUT,
    )
    # Check exit code
    failures = []
    if exit_expected is not None:
        if proc.returncode != exit_expected:
            failures.append(f"EXIT: expected {exit_expected}, got {proc.returncode}")
    
    # Check stdout
    if stdout_expected is not None:
        raw = proc.stdout or b''
        # Take only the first N bytes matching expected length
        actual = raw.decode('ascii', errors='replace').strip()[:len(stdout_expected) + 100]
        if actual != stdout_expected.strip():
            failures.append(f"STDOUT: expected {stdout_expected!r}, got {actual!r}")
    
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
    examples = sorted(
        f for f in os.listdir(EXAMPLES_DIR) if f.endswith(".ep")
    )
    if not examples:
        print("No .ep files found in examples/")
        return 0, 1, 0

    passed = 0
    failed = 0
    skipped = 0

    print(f"Running {len(examples)} tests...\n")
    for ep_name in examples:
        ep_path = os.path.join(EXAMPLES_DIR, ep_name)
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
        print(f"  {status:5}  {ep_name:20s}  {detail}")

    print(f"\n{passed} passed, {failed} failed, {skipped} skipped")
    return passed, failed, skipped


def main():
    ensure_current_compiler()
    _, failed, _ = run_all()
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
