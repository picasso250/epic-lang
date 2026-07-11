#!/usr/bin/env python3
"""Check that the compiler reaches a fixed point from the frozen v0 seed."""

import argparse
import filecmp
import os
import shutil
import subprocess
import sys
import time

from compiler_sources import SELF_HOST_COMPILER_SOURCES, SELF_HOST_RUNTIME_SOURCES


def rel(path):
    return os.path.relpath(path, SCRIPT_DIR).replace(os.sep, "/")


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BUILD_DIR = os.path.join(SCRIPT_DIR, "build")
BOOT_DIR = os.path.join(BUILD_DIR, "fixed-point")
DEFAULT_SEED = os.path.join(BUILD_DIR, "bootstrap-v0", "epic-v0.exe")
RUNTIME_SOURCES = list(SELF_HOST_RUNTIME_SOURCES)
COMPILER_SOURCES = [path.replace("/", os.sep) for path in SELF_HOST_COMPILER_SOURCES]

TIMEOUT_SECONDS = int(os.environ.get("BOOTSTRAP_TIMEOUT", "30"))


def format_size(num_bytes):
    return f"{num_bytes:,} bytes ({num_bytes / (1024 * 1024):.2f} MiB)"


def print_exe_size(path, label):
    print(f"  {label} exe size: {format_size(os.path.getsize(path))}", flush=True)


def remove_tree_with_retry(path, attempts=5):
    for attempt in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except PermissionError:
            if attempt + 1 == attempts:
                raise
            time.sleep(1)


def process_peak_memory(process):
    """Return Windows peak working-set and committed bytes for a Popen process."""
    if os.name != "nt":
        return None

    import ctypes
    from ctypes import wintypes

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    get_process_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
    get_process_memory_info.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessMemoryCounters),
        wintypes.DWORD,
    ]
    get_process_memory_info.restype = wintypes.BOOL
    if not get_process_memory_info(process._handle, ctypes.byref(counters), counters.cb):
        raise ctypes.WinError()
    return counters.PeakWorkingSetSize, counters.PeakPagefileUsage


def run_checked(cmd, label):
    start = time.perf_counter()
    process = subprocess.Popen(
        cmd,
        cwd=SCRIPT_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        stdout, stderr = process.communicate(timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        stdout, stderr = process.communicate()
        raise RuntimeError(
            f"{label} timed out after {TIMEOUT_SECONDS}s\n"
            + stdout[-4000:]
            + stderr[-4000:]
        ) from exc
    peak_memory = process_peak_memory(process)
    result = subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)
    if result.returncode != 0:
        raise RuntimeError(
            f"{label} failed with exit {result.returncode}\n"
            + "cmd: " + " ".join(cmd) + "\n"
            + f"stdout bytes: {len(result.stdout)} stderr bytes: {len(result.stderr)}\n"
            + "--- stdout tail ---\n"
            + result.stdout[-8000:]
            + "\n--- stderr tail ---\n"
            + result.stderr[-8000:]
        )
    elapsed = time.perf_counter() - start
    for line in result.stdout.splitlines():
        if line.startswith("  timing: ") or line.startswith("  stats: "):
            print(f"  {label} {line.strip()}", flush=True)
    if peak_memory is not None:
        peak_working_set, peak_commit = peak_memory
        print(
            f"  {label} memory: peak working set={format_size(peak_working_set)} "
            + f"peak commit={format_size(peak_commit)}",
            flush=True,
        )
    print(f"{label}: {elapsed:.2f}s", flush=True)
    return result


def build_with_epic(compiler, output_path, label):
    run_checked(
        [
            compiler,
            *RUNTIME_SOURCES,
            *COMPILER_SOURCES,
            "--main",
            os.path.join("src", "epic.ep"),
            "-o",
            rel(output_path),
            "--verbose",
        ],
        label,
    )
    if not os.path.exists(output_path):
        raise RuntimeError(f"expected compiler output missing: {output_path}")
    print_exe_size(output_path, label)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--seed",
        help="existing Epic seed compiler (default: frozen build/bootstrap-v0/epic-v0.exe)",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="write the converged compiler to this path after verification",
    )
    return parser.parse_args()


def write_output(source_path, destination_path):
    destination = os.path.abspath(destination_path)
    parent = os.path.dirname(destination)
    if parent:
        os.makedirs(parent, exist_ok=True)
    shutil.copyfile(source_path, destination)
    print(f"wrote converged compiler: {destination}", flush=True)


def resolve_seed(requested):
    seed = os.path.abspath(requested or DEFAULT_SEED)
    if os.path.isfile(seed):
        return seed
    if requested:
        raise RuntimeError(f"bootstrap seed compiler does not exist: {seed}")
    build_script = os.path.join(SCRIPT_DIR, "build_epic_v0.py")
    run_checked(
        [sys.executable, build_script, "--require-expected"],
        "rebuild frozen v0 seed",
    )
    if not os.path.isfile(seed):
        raise RuntimeError(f"v0 rebuild did not produce seed compiler: {seed}")
    return seed


def main():
    args = parse_args()
    if os.path.exists(BOOT_DIR):
        remove_tree_with_retry(BOOT_DIR)
    os.makedirs(BOOT_DIR, exist_ok=True)

    seed = resolve_seed(args.seed)
    generation1 = os.path.join(BOOT_DIR, "epic-seed-1.exe")
    generation2 = os.path.join(BOOT_DIR, "epic-seed-2.exe")
    generation3 = os.path.join(BOOT_DIR, "epic-seed-3.exe")

    build_with_epic(seed, generation1, "v0 seed -> epic-seed-1")
    build_with_epic(generation1, generation2, "epic-seed-1 -> epic-seed-2")
    build_with_epic(generation2, generation3, "epic-seed-2 -> epic-seed-3")

    checks = [(generation2, generation3)]
    converged = generation3

    for left, right in checks:
        if not filecmp.cmp(left, right, shallow=False):
            raise RuntimeError(
                "bootstrap output is not byte-identical: "
                + os.path.basename(left)
                + " != "
                + os.path.basename(right)
            )

    print("bootstrap fixed point reached")
    if args.output:
        write_output(converged, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
