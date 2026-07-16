#!/usr/bin/env python3
"""Cache fixed-point self-host compiler builds and equivalent benchmark results."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
COMPILER_SOURCES = [path.relative_to(ROOT).as_posix() for path in sorted((ROOT / "src").glob("*.ep"))]
DEFAULT_SEED = ROOT / "build" / "bootstrap-v0" / "epic-v0.exe"
DEFAULT_CACHE_ROOT = ROOT / "build" / "cache" / "self-host-benchmark"
BENCH_DIR = ROOT / "build" / "self-host-benchmark"
BENCH_COMPILER = BENCH_DIR / "compiler.exe"
BENCH_OUTPUT = BENCH_DIR / "epic.exe"
RUNTIME_BUNDLE_SOURCE = "src/runtime_bundle.ep"
CACHE_SCHEMA = 3
BOOTSTRAP_CONTRACT = "fixed-point-embedded-runtime-v2"
BENCHMARK_CONTRACT = "self-host-compiler-v3-rdata"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(relative: str) -> dict[str, Any]:
    path = ROOT / relative
    if not path.is_file():
        raise RuntimeError(f"cache input does not exist: {relative}")
    return {
        "path": relative.replace(os.sep, "/"),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def group_record(paths: list[str]) -> dict[str, Any]:
    files = [file_record(path) for path in paths]
    encoded = json.dumps(files, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return {
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "files": files,
    }


def embedded_runtime_paths() -> list[str]:
    bundle = ROOT / RUNTIME_BUNDLE_SOURCE
    text = bundle.read_text(encoding="utf-8")
    paths: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r'\bembed\s+"([^"]+)"', text):
        resolved = (bundle.parent / match.group(1)).resolve()
        try:
            relative = resolved.relative_to(ROOT.resolve()).as_posix()
        except ValueError as exc:
            raise RuntimeError(f"embedded runtime path escapes repository: {match.group(1)}") from exc
        if relative not in seen:
            seen.add(relative)
            paths.append(relative)
    if not paths:
        raise RuntimeError(f"no embed expressions found in {RUNTIME_BUNDLE_SOURCE}")
    return paths


def host_record() -> dict[str, Any]:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": platform.python_version(),
        "processor_identifier": os.environ.get("PROCESSOR_IDENTIFIER", ""),
        "number_of_processors": os.environ.get("NUMBER_OF_PROCESSORS", ""),
    }


def resolve_seed(requested: str | None) -> Path:
    seed = Path(requested).resolve() if requested else DEFAULT_SEED
    if seed.is_file():
        return seed
    if requested:
        raise RuntimeError(f"seed compiler does not exist: {seed}")
    completed = subprocess.run(
        [sys.executable, "build_epic_v0.py"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0 or not seed.is_file():
        raise RuntimeError("failed to rebuild v0 branch seed")
    return seed


def build_inputs(seed: Path) -> dict[str, Any]:
    runtime_sources = embedded_runtime_paths()
    return {
        "schema": CACHE_SCHEMA,
        "bootstrap_contract": BOOTSTRAP_CONTRACT,
        "seed": {
            "sha256": sha256_file(seed),
            "bytes": seed.stat().st_size,
        },
        "compiler_sources": group_record(COMPILER_SOURCES),
        "runtime_sources": group_record(runtime_sources),
        "tools": group_record(["bootstrap_fixed_point.py"]),
        "source_order": {
            "embedded_runtime": runtime_sources,
            "compiler": list(COMPILER_SOURCES),
            "main": "src/epic.ep",
        },
        "target": {
            "system": platform.system(),
            "machine": platform.machine(),
        },
    }


def benchmark_inputs(build_key: str, runs: int) -> dict[str, Any]:
    return {
        "schema": CACHE_SCHEMA,
        "benchmark_contract": BENCHMARK_CONTRACT,
        "build_key": build_key,
        "runs": runs,
        "tool": file_record(Path(__file__).relative_to(ROOT).as_posix()),
        "host": host_record(),
        "command": {
            "embedded_runtime": embedded_runtime_paths(),
            "compiler": list(COMPILER_SOURCES),
            "main": "src/epic.ep",
            "output": BENCH_OUTPUT.relative_to(ROOT).as_posix(),
            "verbose": True,
        },
    }


def content_key(inputs: dict[str, Any]) -> str:
    encoded = json.dumps(inputs, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def run_capture(command: list[str], log_path: Path, *, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    log_path.write_text(
        "command: " + subprocess.list2cmdline(command) + "\n\n"
        + "--- stdout ---\n" + completed.stdout
        + "\n--- stderr ---\n" + completed.stderr,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed with exit {completed.returncode}: {subprocess.list2cmdline(command)}\n"
            + completed.stdout[-4000:] + completed.stderr[-4000:]
        )
    return completed


def build_fixed_point(seed: Path, compiler_output: Path, log_path: Path) -> None:
    command = [
        sys.executable,
        "bootstrap_fixed_point.py",
        "--seed",
        str(seed),
        "-o",
        str(compiler_output),
    ]
    completed = run_capture(command, log_path)
    print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    if not compiler_output.is_file():
        raise RuntimeError("fixed-point build did not produce the converged compiler")


def benchmark_command() -> list[str]:
    return [
        str(BENCH_COMPILER),
        *COMPILER_SOURCES,
        "--main",
        "src/epic.ep",
        "-o",
        BENCH_OUTPUT.relative_to(ROOT).as_posix(),
        "--verbose",
    ]


def parse_benchmark_row(stdout: str, elapsed_ns: int) -> dict[str, Any]:
    x64_match = re.search(r"lower counts:.*x64_items=(\d+)", stdout)
    text_match = re.search(r"machine counts:.*text_bytes=(\d+)", stdout)
    rdata_match = re.search(r"machine counts:.*rdata_bytes=(\d+)", stdout)
    data_match = re.search(r"machine counts:.*data_bytes=(\d+)", stdout)
    total_match = re.search(r"timing: total: (\d+) ms", stdout)
    if not x64_match or not text_match or not data_match or not total_match:
        raise RuntimeError("compiler output is missing benchmark metrics\n" + stdout[-8000:])
    return {
        "wall_ms": elapsed_ns / 1_000_000,
        "internal_ms": int(total_match.group(1)),
        "x64_items": int(x64_match.group(1)),
        "text_bytes": int(text_match.group(1)),
        "rdata_bytes": int(rdata_match.group(1)) if rdata_match else 0,
        "data_bytes": int(data_match.group(1)),
        "exe_bytes": BENCH_OUTPUT.stat().st_size,
    }


def run_benchmark(compiler: Path, runs: int, log_dir: Path) -> list[dict[str, Any]]:
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(compiler, BENCH_COMPILER)
    command = benchmark_command()
    rows: list[dict[str, Any]] = []
    for index in range(runs):
        start = time.perf_counter_ns()
        completed = run_capture(command, log_dir / f"benchmark-run-{index + 1}.txt")
        elapsed_ns = time.perf_counter_ns() - start
        row = parse_benchmark_row(completed.stdout, elapsed_ns)
        rows.append(row)
        print(render_run("benchmark", index + 1, row))
    for metric in ("x64_items", "text_bytes", "rdata_bytes", "data_bytes", "exe_bytes"):
        values = {row[metric] for row in rows}
        if len(values) != 1:
            raise RuntimeError(f"non-deterministic {metric}: {sorted(values)}")
    return rows


def result_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "median_wall_ms": statistics.median(row["wall_ms"] for row in rows),
        "median_internal_ms": statistics.median(row["internal_ms"] for row in rows),
        "x64_items": rows[0]["x64_items"],
        "text_bytes": rows[0]["text_bytes"],
        "rdata_bytes": rows[0]["rdata_bytes"],
        "data_bytes": rows[0]["data_bytes"],
        "exe_bytes": rows[0]["exe_bytes"],
    }


def render_run(label: str, index: int, row: dict[str, Any]) -> str:
    return (
        f"{label} run {index}: wall_ms={row['wall_ms']:.4f} "
        f"internal_ms={row['internal_ms']} x64_items={row['x64_items']} "
        f"text_bytes={row['text_bytes']} rdata_bytes={row['rdata_bytes']} "
        f"data_bytes={row['data_bytes']} "
        f"exe_bytes={row['exe_bytes']}"
    )


def render_result(
    result: dict[str, Any],
    build: dict[str, Any],
    label: str,
    build_status: str,
    result_status: str,
) -> str:
    lines = [
        f"build cache {build_status}: {build['key']}",
        f"result cache {result_status}: {result['key']}",
        f"created_utc={result['created_utc']}",
        f"seed_sha256={build['inputs']['seed']['sha256']}",
        f"compiler_sources_sha256={build['inputs']['compiler_sources']['sha256']}",
        f"runtime_sources_sha256={build['inputs']['runtime_sources']['sha256']}",
    ]
    for index, row in enumerate(result["runs"], 1):
        lines.append(render_run(label, index, row))
    summary = result["summary"]
    lines.extend(
        [
            f"{label} median_wall_ms={summary['median_wall_ms']:.3f}",
            f"{label} median_internal_ms={summary['median_internal_ms']:.0f}",
            f"{label} x64_items=[{summary['x64_items']}]",
            f"{label} text_bytes=[{summary['text_bytes']}]",
            f"{label} rdata_bytes=[{summary['rdata_bytes']}]",
            f"{label} data_bytes=[{summary['data_bytes']}]",
            f"{label} exe_bytes=[{summary['exe_bytes']}]",
        ]
    )
    return "\n".join(lines) + "\n"


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_build(cache_dir: Path, key: str) -> dict[str, Any] | None:
    manifest = load_json(cache_dir / "manifest.json")
    compiler = cache_dir / "compiler.exe"
    if manifest is None or not compiler.is_file() or manifest.get("key") != key:
        return None
    expected = manifest.get("compiler", {}).get("sha256")
    if not expected or sha256_file(compiler) != expected:
        return None
    return manifest


def load_result(cache_dir: Path, key: str, build_key: str) -> dict[str, Any] | None:
    result = load_json(cache_dir / "result.json")
    if result is None or result.get("key") != key or result.get("build_key") != build_key:
        return None
    return result


def replace_cache(temp_dir: Path, cache_dir: Path) -> None:
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
    temp_dir.replace(cache_dir)


def ensure_build(
    seed: Path,
    inputs: dict[str, Any],
    key: str,
    cache_root: Path,
    rebuild: bool,
) -> tuple[dict[str, Any], Path, str]:
    builds_root = cache_root / "builds"
    cache_dir = builds_root / key
    cached = None if rebuild else load_build(cache_dir, key)
    if cached is not None:
        return cached, cache_dir / "compiler.exe", "hit"

    builds_root.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=f".{key[:12]}-", dir=builds_root))
    try:
        compiler = temp_dir / "compiler.exe"
        print(f"build cache miss: {key}")
        build_fixed_point(seed, compiler, temp_dir / "fixed-point.txt")
        manifest = {
            "schema": CACHE_SCHEMA,
            "key": key,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "inputs": inputs,
            "compiler": {
                "sha256": sha256_file(compiler),
                "bytes": compiler.stat().st_size,
            },
        }
        (temp_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        replace_cache(temp_dir, cache_dir)
        return manifest, cache_dir / "compiler.exe", "stored"
    except Exception:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", help="seed compiler; default is the reproducible v0 branch compiler")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--label", default="self-host")
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_ROOT))
    parser.add_argument("--refresh", action="store_true", help="rerun benchmark but reuse the fixed-point compiler")
    parser.add_argument("--rebuild", action="store_true", help="rebuild fixed point and rerun benchmark")
    parser.add_argument("--key-only", action="store_true", help="print the benchmark content key without building")
    parser.add_argument("--show-keys", action="store_true", help="print both build and benchmark content keys")
    parser.add_argument("-o", "--output", help="copy the cached converged compiler to this path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.runs <= 0:
        raise RuntimeError("--runs must be positive")

    seed = resolve_seed(args.seed)
    build_input = build_inputs(seed)
    build_key = content_key(build_input)
    benchmark_input = benchmark_inputs(build_key, args.runs)
    result_key = content_key(benchmark_input)
    if args.key_only:
        print(result_key)
        return 0
    if args.show_keys:
        print(f"build_key={build_key}")
        print(f"result_key={result_key}")
        return 0

    cache_root = Path(args.cache_dir).resolve()
    build, compiler, build_status = ensure_build(
        seed,
        build_input,
        build_key,
        cache_root,
        args.rebuild,
    )

    results_root = cache_root / "results"
    result_dir = results_root / result_key
    result = None if args.refresh or args.rebuild else load_result(result_dir, result_key, build_key)
    if result is not None:
        print(render_result(result, build, args.label, build_status, "hit"), end="")
    else:
        results_root.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(tempfile.mkdtemp(prefix=f".{result_key[:12]}-", dir=results_root))
        try:
            print(f"result cache miss: {result_key}")
            rows = run_benchmark(compiler, args.runs, temp_dir)
            result = {
                "schema": CACHE_SCHEMA,
                "key": result_key,
                "build_key": build_key,
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "inputs": benchmark_input,
                "runs": rows,
                "summary": result_summary(rows),
            }
            (temp_dir / "result.json").write_text(
                json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (temp_dir / "report.txt").write_text(
                render_result(result, build, "self-host", build_status, "stored"),
                encoding="utf-8",
            )
            replace_cache(temp_dir, result_dir)
            print(render_result(result, build, args.label, build_status, "stored"), end="")
        except Exception:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            raise

    if args.output:
        destination = Path(args.output).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(compiler, destination)
        print(f"wrote cached converged compiler: {destination}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
