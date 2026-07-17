"""Run a Windows process and report its elapsed time and peak working set."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
import subprocess
import time


PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010


class ProcessMemoryCounters(ctypes.Structure):
    _fields_ = (
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
    )


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
open_process = kernel32.OpenProcess
open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
open_process.restype = wintypes.HANDLE
close_handle = kernel32.CloseHandle
close_handle.argtypes = (wintypes.HANDLE,)
close_handle.restype = wintypes.BOOL

psapi = ctypes.WinDLL("psapi", use_last_error=True)
get_process_memory_info = psapi.GetProcessMemoryInfo
get_process_memory_info.argtypes = (
    wintypes.HANDLE,
    ctypes.POINTER(ProcessMemoryCounters),
    wintypes.DWORD,
)
get_process_memory_info.restype = wintypes.BOOL


@dataclass(frozen=True)
class ProcessMetrics:
    elapsed_seconds: float
    peak_working_set_bytes: int


def run_measured(command: list[str], *, cwd: Path) -> ProcessMetrics:
    start = time.perf_counter()
    process = subprocess.Popen(command, cwd=cwd)
    handle = open_process(
        PROCESS_QUERY_INFORMATION | PROCESS_VM_READ,
        False,
        process.pid,
    )
    if not handle:
        process.kill()
        process.wait()
        raise ctypes.WinError(ctypes.get_last_error())

    try:
        returncode = process.wait()
        elapsed = time.perf_counter() - start
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        if not get_process_memory_info(handle, ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        close_handle(handle)

    if returncode != 0:
        raise subprocess.CalledProcessError(returncode, command)
    return ProcessMetrics(elapsed, counters.PeakWorkingSetSize)


def format_peak_working_set(byte_count: int) -> str:
    return f"{byte_count / (1024 * 1024):.1f} MiB"
