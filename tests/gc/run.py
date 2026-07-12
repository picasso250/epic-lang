#!/usr/bin/env python3
"""Automatic GC retention and bounded-memory stress test."""

import ctypes
import re
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from compiler_runner import compile_program


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


def peak_working_set(process):
    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    if not ctypes.windll.psapi.GetProcessMemoryInfo(process._handle, ctypes.byref(counters), counters.cb):
        raise ctypes.WinError()
    return counters.PeakWorkingSetSize


def run_case(name, expected, limit_mib):
    source = ROOT / "tests" / "gc" / f"{name}.ep"
    exe = compile_program(source, ROOT / "build" / "tests" / f"gc-{name}.exe")
    process = subprocess.Popen([str(exe)], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate(timeout=60)
    peak = peak_working_set(process)
    stderr_lines = [line for line in stderr.splitlines() if line]
    timing_lines = [line for line in stderr_lines if re.fullmatch(rb"gc stw: \d+ ms", line)]
    profile_pattern = re.compile(
        rb"gc alloc profile: total_count=(\d+) total_bytes=(\d+) "
        rb"le8_count=(\d+) le8_bytes=(\d+) le16_count=(\d+) le16_bytes=(\d+) "
        rb"le24_count=(\d+) le24_bytes=(\d+) le32_count=(\d+) le32_bytes=(\d+) "
        rb"le64_count=(\d+) le64_bytes=(\d+) exact16_count=(\d+) "
        rb"exact24_count=(\d+) exact32_count=(\d+)"
    )
    profile_matches = [profile_pattern.fullmatch(line) for line in stderr_lines]
    profile_matches = [match for match in profile_matches if match]
    known_lines = len(timing_lines) + len(profile_matches) == len(stderr_lines)
    profile_ok = False
    if len(profile_matches) == 1:
        values = [int(value) for value in profile_matches[0].groups()]
        profile_ok = (
            0 <= values[2] <= values[4] <= values[6] <= values[8] <= values[10] <= values[0]
            and 0 <= values[3] <= values[5] <= values[7] <= values[9] <= values[11] <= values[1]
            and 0 <= values[12] <= values[4]
            and 0 <= values[13] <= values[6]
            and 0 <= values[14] <= values[8]
        )
    timings_ok = bool(timing_lines)
    if process.returncode != 0 or stdout.strip() != expected or not timings_ok or not profile_ok or not known_lines:
        print(f"  FAIL  GC {name} behavior, STW timing, or allocation profile")
        print((stdout + stderr).decode("utf-8", errors="replace")[-2000:])
        return False
    limit = limit_mib * 1024 * 1024
    if peak > limit:
        print(f"  FAIL  GC {name} peak memory {peak / 1024 / 1024:.1f} MiB > {limit_mib} MiB")
        return False
    print(f"  PASS  GC {name} peak memory {peak / 1024 / 1024:.1f} MiB")
    return True


def main():
    ok = run_case("stress", b"gc stress ok", 256)
    ok = run_case("tiny", b"gc tiny ok", 128) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
