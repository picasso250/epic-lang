#!/usr/bin/env python3
"""Compare Epic lexer output against reference Python lexer for all .ep files."""

import os, sys, subprocess, glob

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EPICC = os.path.join(SCRIPT_DIR, "epicc.py")
LEXER_EP = os.path.join(SCRIPT_DIR, "lexer.ep")

sys.path.insert(0, SCRIPT_DIR)
from lexer import lex as py_lex


def build_epic_lexer_for(target_ep):
    """Patch lexer.ep to read target_ep, compile, return exe path."""
    with open(LEXER_EP, encoding="utf-8") as f:
        src = f.read()
    src = src.replace('"examples/m1_exit.ep"', f'"{target_ep}"')
    tmp_ep = os.path.join(SCRIPT_DIR, "_test_lex.ep")
    with open(tmp_ep, "w", encoding="utf-8") as f:
        f.write(src)

    result = subprocess.run(
        [sys.executable, EPICC, tmp_ep],
        capture_output=True, text=True, cwd=SCRIPT_DIR,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Compile failed:\n{result.stderr[:500]}")
    return os.path.join(SCRIPT_DIR, "_test_lex.exe")


def main():
    ep_files = sorted(glob.glob(os.path.join(SCRIPT_DIR, "examples", "*.ep")))
    if not ep_files:
        print("No .ep files found")
        return

    passed = 0
    failed = 0

    print(f"Testing Epic lexer against Python lexer on {len(ep_files)} files...\n")

    for ep_file in ep_files:
        name = os.path.basename(ep_file)

        # Python reference
        with open(ep_file, encoding="utf-8") as f:
            py_src = f.read()
        py_tokens = py_lex(py_src)
        py_out = "\n".join(f"{k} {v} {l}" for k, v, l in py_tokens)

        # Epic lexer
        try:
            exe = build_epic_lexer_for(ep_file)
        except RuntimeError as e:
            print(f"  FAIL  {name:30s} COMPILE ERROR: {e}")
            failed += 1
            continue

        proc = subprocess.run([exe], capture_output=True, cwd=SCRIPT_DIR)
        ep_out = proc.stdout.decode("ascii", errors="replace").strip()

        if py_out == ep_out:
            print(f"  PASS  {name:30s} {len(py_tokens)} tokens")
            passed += 1
        else:
            print(f"  FAIL  {name:30s} {len(py_tokens)} tokens — diff:")
            py_lines = py_out.split("\n")
            ep_lines = ep_out.split("\n")
            diff_count = 0
            for i in range(max(len(py_lines), len(ep_lines))):
                a = py_lines[i] if i < len(py_lines) else "MISSING"
                b = ep_lines[i] if i < len(ep_lines) else "MISSING"
                if a != b:
                    print(f"         line {i}: {a!r} vs {b!r}")
                    diff_count += 1
                    if diff_count >= 3:
                        print(f"         ... and more")
                        break
            failed += 1

        # Cleanup
        for ext in [".asm", ".obj", ".exe"]:
            try:
                os.remove(os.path.join(SCRIPT_DIR, "_test_lex" + ext))
            except OSError:
                pass

    print(f"\n{passed} passed, {failed} failed, {len(ep_files)} total")


if __name__ == "__main__":
    main()
