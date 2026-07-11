#!/usr/bin/env python3
"""Automatic GC retention and bounded-memory stress test."""

import ctypes
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


def main():
    source = ROOT / "tests" / "gc" / "stress.ep"
    exe = compile_program(source, ROOT / "build" / "tests" / "gc-stress.exe")
    process = subprocess.Popen([str(exe)], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate(timeout=60)
    peak = peak_working_set(process)
    if process.returncode != 0 or stdout.strip() != b"gc stress ok":
        print("  FAIL  GC stress behavior")
        print((stdout + stderr).decode("utf-8", errors="replace")[-2000:])
        return 1
    limit = 512 * 1024 * 1024
    if peak > limit:
        print(f"  FAIL  GC stress peak memory {peak / 1024 / 1024:.1f} MiB > 512 MiB")
        return 1
    print(f"  PASS  GC stress peak memory {peak / 1024 / 1024:.1f} MiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
