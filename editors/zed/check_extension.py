from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXTENSION = ROOT / "editors" / "zed" / "extension.toml"
GRAMMAR_FILES = (
    "grammar.js",
    "src/grammar.json",
    "src/node-types.json",
    "src/parser.c",
)


def git_show(revision: str, path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{revision}:{path}"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise SystemExit(f"cannot read grammar revision {revision}: {message}")
    return result.stdout


def main() -> int:
    config = tomllib.loads(EXTENSION.read_text(encoding="utf-8"))
    grammar = config["grammars"]["epic"]
    revision = grammar["rev"]
    grammar_root = grammar["path"]

    mismatches: list[str] = []
    for relative in GRAMMAR_FILES:
        repo_path = f"{grammar_root}/{relative}"
        current = (ROOT / repo_path).read_bytes().replace(b"\r\n", b"\n")
        pinned = git_show(revision, repo_path).replace(b"\r\n", b"\n")
        if current != pinned:
            mismatches.append(repo_path)

    if mismatches:
        joined = "\n  ".join(mismatches)
        raise SystemExit(
            "extension.toml pins a stale Epic grammar revision. "
            "Point grammars.epic.rev at a commit containing the current grammar files:\n  "
            + joined
        )

    print(f"PASS Zed grammar revision {revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
