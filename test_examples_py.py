#!/usr/bin/env python3
"""
Example test runner for the Python reference compiler.
Scans examples/*.ep, reads # EXIT and # STDOUT annotations,
compiles through bootstrap/epic.py, runs, and reports pass/fail.
"""

import os, sys, subprocess, re, shlex, argparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EPICC = os.path.join(SCRIPT_DIR, "bootstrap", "epic.py")
EXAMPLES_DIR = os.path.join(SCRIPT_DIR, "examples")
EXEC_TIMEOUT = 1  # seconds, prevent link.py bugs from hanging
SELF_HOST_BUILD_DIR = os.path.join(SCRIPT_DIR, "build", "self_hosted_examples")
SELF_HOST_COMPILER_DIR = os.path.join(SCRIPT_DIR, "build", "self_hosted_compiler")
SELF_HOST_COMPILER_EXE = os.path.join(SELF_HOST_COMPILER_DIR, "src", "epic.exe")
SELF_HOST_COMPILER_SOURCES = [
    "src/util.ep",
    "src/lexer.ep",
    "src/parser.ep",
    "src/sema.ep",
    "src/mir.ep",
    "src/mir_runtime.ep",
    "src/ast_to_mir.ep",
    "src/x64.ep",
    "src/mir_to_x64.ep",
    "src/x64_runtime.ep",
    "src/machine.ep",
    "src/coff.ep",
    "src/link.ep",
    "src/epic.ep",
]
SELF_HOST_RUNTIME_SOURCES = [
    "runtime/str.ep",
]


def parse_annotations(source):
    """Extract test annotations from # comments."""
    exit_code = None
    stdout_lines = []
    argv = []
    clean_paths = []
    compile_fail = None
    compile_only = False
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
        elif m := re.match(r'#\s*COMPILE_FAIL:\s*(.*)$', line):
            compile_fail = m.group(1).strip() or ""
        elif re.match(r'#\s*COMPILE_ONLY\b', line):
            compile_only = True
    stdout = "\n".join(stdout_lines) if stdout_lines else None
    return exit_code, stdout, argv, clean_paths, compile_fail, compile_only


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


def compile_self_hosted_compiler():
    """Build the EP compiler using the Python stage-0 compiler."""
    os.makedirs(SELF_HOST_COMPILER_DIR, exist_ok=True)
    cmd = [
        sys.executable,
        EPICC,
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
    """Compile and run one .ep file using an already-built EP compiler."""
    with open(ep_file, "r", encoding="utf-8") as f:
        source = f.read()
    exit_expected, stdout_expected, argv, clean_paths, compile_fail, compile_only = parse_annotations(source)

    if exit_expected is None and stdout_expected is None and compile_fail is None and not compile_only:
        return True, "no annotations — skipped"
    if compile_fail is not None:
        return True, "compile-fail case skipped for self-hosted examples"

    try:
        clean_test_paths(clean_paths)
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
        *SELF_HOST_RUNTIME_SOURCES,
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
    if compile_only:
        return True, "compile only"
    if not os.path.exists(exe_path):
        return False, f"no exe produced: {exe_path}"

    proc = subprocess.run(
        [exe_path, *argv],
        capture_output=True,
        cwd=SCRIPT_DIR,
        timeout=EXEC_TIMEOUT,
    )
    failures = []
    if exit_expected is not None and proc.returncode != exit_expected:
        failures.append(f"EXIT: expected {exit_expected}, got {proc.returncode}")
    if stdout_expected is not None:
        raw = proc.stdout or b''
        actual = raw.decode('ascii', errors='replace').strip()[:len(stdout_expected) + 100]
        if actual != stdout_expected.strip():
            failures.append(f"STDOUT: expected {stdout_expected!r}, got {actual!r}")
    try:
        clean_test_paths(clean_paths)
    except RuntimeError as e:
        failures.append(str(e))
    if failures:
        return False, "; ".join(failures)
    return True, "OK"


def run_test(ep_file, linker="lld-link"):
    """Compile and run a single .ep file, return (pass, detail)."""
    with open(ep_file, "r", encoding="utf-8") as f:
        source = f.read()
    exit_expected, stdout_expected, argv, clean_paths, compile_fail, compile_only = parse_annotations(source)
    
    if exit_expected is None and stdout_expected is None and compile_fail is None and not compile_only:
        return True, "no annotations — skipped"

    try:
        clean_test_paths(clean_paths)
    except RuntimeError as e:
        return False, str(e)
    
    # Compile
    result = subprocess.run(
        [sys.executable, EPICC, ep_file, "--linker", linker],
        capture_output=True, text=True, cwd=SCRIPT_DIR, timeout=30,
    )
    if compile_fail is not None:
        output = result.stdout + result.stderr
        if result.returncode == 0:
            return False, "compile succeeded, expected failure"
        if compile_fail and compile_fail not in output:
            return False, f"compile failed, but expected {compile_fail!r} in:\n{output[:500]}"
        return True, "compile failed as expected"
    if result.returncode != 0:
        return False, f"compile failed:\n{result.stderr[:500]}"
    if compile_only:
        return True, "compile only"
    
    rel = os.path.relpath(ep_file, SCRIPT_DIR)
    exe_path = os.path.join(SCRIPT_DIR, "build", os.path.splitext(rel)[0] + ".exe")
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


def run_all(linker, self_hosted=False, compiler_exe=None):
    examples = sorted(
        f for f in os.listdir(EXAMPLES_DIR) if f.endswith(".ep")
    )
    if not examples:
        print("No .ep files found in examples/")
        return 0, 1, 0

    passed = 0
    failed = 0
    skipped = 0

    mode = "self-hosted" if self_hosted else "python"
    print(f"Running {len(examples)} tests ({mode})...\n")
    for ep_name in examples:
        ep_path = os.path.join(EXAMPLES_DIR, ep_name)
        try:
            if self_hosted:
                ok, detail = run_test_self_hosted(ep_path, compiler_exe)
            else:
                ok, detail = run_test(ep_path, linker=linker)
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
    parser = argparse.ArgumentParser(description="Epic Python example test runner")
    parser.add_argument("example", nargs="?", help="exact example name or .ep path")
    parser.add_argument("--linker", choices=["lld", "py"], default="py",
                        help="Which linker to use (default: py)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--py-only", action="store_true",
                      help="Run examples with the Python reference compiler only (default)")
    mode.add_argument("--self-hosted", action="store_true",
                      help="Build src/epic.ep with Python, then use that EP compiler for examples")
    args = parser.parse_args()

    ep_path = resolve_example(args.example)
    linker_val = "lld-link" if args.linker == "lld" else "py"

    compiler_exe = None
    if args.self_hosted:
        compiler_exe = compile_self_hosted_compiler()

    if ep_path is not None:
        # Single example mode
        try:
            if args.self_hosted:
                ok, detail = run_test_self_hosted(ep_path, compiler_exe)
            else:
                ok, detail = run_test(ep_path, linker=linker_val)
        except subprocess.TimeoutExpired:
            ok, detail = False, "TIMEOUT (compile >30s)"
        except Exception as e:
            ok, detail = False, f"exception: {e}"
        status = "PASS" if ok else "FAIL"
        if "skipped" in detail:
            status = "SKIP"
        name = os.path.relpath(ep_path, EXAMPLES_DIR)
        print(f"  {status:5}  {name:20s}  {detail}")
        sys.exit(0 if ok else 1)
    else:
        _, failed, _ = run_all(linker_val, self_hosted=args.self_hosted, compiler_exe=compiler_exe)
        sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
