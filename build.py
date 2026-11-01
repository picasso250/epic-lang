#!/usr/bin/env python3
"""Build Epic's compiler generations from directories, without Git or worktrees.

The five generations are separate source roots. vN is compiled by v(N-1),
not by itself. v0 is a Python stage-0, used only for the v1 seed. v4 can
additionally verify its own fixed point using v4/bootstrap_fixed_point.py.

The external trusted NASM binary is needed ONLY by Python v0. Place nasm.exe in
v0/tools/ (ignored by Git) or set EPIC_NASM to an existing executable path.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
SOURCE_V1 = ('epic.ep', 'lexer.ep', 'parser.ep', 'codegen.ep', 'asm.ep', 'pe.ep')
SOURCE_V2 = ('epic.ep', 'lexer.ep', 'parser.ep', 'sema.ep', 'codegen.ep', 'asm.ep', 'pe.ep')


def source_paths(version: int) -> list[str]:
    root = ROOT / f'v{version}'
    if version == 1:
        names = SOURCE_V1
    elif version == 2:
        names = SOURCE_V2
    else:
        names = sorted((p.name for p in (root / 'src').glob('*.ep')),
                       key=lambda name: (name != 'epic.ep', name))
    paths = [f'src/{name}' for name in names]
    missing = [path for path in paths if not (root / path).is_file()]
    if missing:
        raise RuntimeError(f'v{version} missing source files: {missing}')
    return paths


def compiler_path(version: int) -> Path:
    return ROOT / f'v{version}' / 'build' / f'epic-v{version}.exe'


def run(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def ensure_nasm() -> Path:
    target = ROOT / 'v0' / 'tools' / 'nasm.exe'
    if target.is_file():
        return target
    supplied = os.environ.get('EPIC_NASM')
    if not supplied:
        raise RuntimeError('Missing trusted NASM: place nasm.exe at v0/tools/nasm.exe '
                           'or set EPIC_NASM to an existing executable. '
                           'The binary is not stored in Git.')
    candidate = Path(supplied).expanduser().resolve()
    if not candidate.is_file():
        raise RuntimeError(f'EPIC_NASM points to a missing executable: {candidate}')
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidate, target)
    return target


def build_to(version: int) -> Path:
    """Always rebuild the complete chain; never reuse a stale seed binary."""
    if not 1 <= version <= 4:
        raise ValueError('Supported compiler target generations: v1..v4')
    ensure_nasm()
    start = time.perf_counter()
    for n in range(1, version + 1):
        root = ROOT / f'v{n}'
        output = compiler_path(n)
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            output.unlink()
        paths = source_paths(n)
        print(f'[v{n}] compiling {len(paths)} sources with '
              f'{"Python v0" if n == 1 else f"Epic v{n - 1}"}...', flush=True)
        if n == 1:
            boot = root / 'build' / 'v1-bootstrap'
            boot.mkdir(parents=True, exist_ok=True)
            main_source = root / 'src' / 'epic.ep'
            command = [sys.executable, str(ROOT / 'v0' / 'epic.py'),
                       '--main', str(main_source), '--linker', 'py',
                       '--out-dir', str(boot),
                       *(str(root / path) for path in paths)]
            run(command, cwd=root)
            built = boot / 'epic.exe'
            if not built.is_file():
                raise RuntimeError(f'Python stage-0 failed to produce {built}')
            shutil.copy2(built, output)
        else:
            run([str(compiler_path(n - 1)), '-o', str(output), *paths], cwd=root)
        if not output.is_file() or not output.stat().st_size:
            raise RuntimeError(f'v{n} compiler output missing: {output}')
        print(f'[v{n}] {output.stat().st_size} bytes; '
              f'sha256={hashlib.sha256(output.read_bytes()).hexdigest()}', flush=True)
    print(f'Built through v{version} in {time.perf_counter() - start:.2f}s', flush=True)
    return compiler_path(version)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--to', type=int, choices=(1, 2, 3, 4), default=4)
    parser.add_argument('-o', '--output', type=Path,
                        help='Optional copy of final compiler (relative to caller working directory)')
    args = parser.parse_args()
    result = build_to(args.to)
    if args.output:
        target = args.output.resolve()
        if target != result:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(result, target)
        print(f'Copied final compiler: {target}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
