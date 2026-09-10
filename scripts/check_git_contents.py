#!/usr/bin/env python3
"""Reject prohibited files in the Git candidate set."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

MAX_BYTES = 1_048_576
FORBIDDEN_SUFFIXES = (
    ".pt",
    ".pth",
    ".onnx",
    ".engine",
    ".bin",
    ".tar",
    ".gz",
    ".zst",
    ".zip",
    ".pem",
    ".key",
)
FORBIDDEN_NAMES = {".env", ".git-credentials"}
FORBIDDEN_NAME_PARTS = ("credential", "id_rsa", "id_ed25519")
FORBIDDEN_DIR_PARTS = (
    "datasets/",
    "derived/",
    "outputs/",
    "runs/",
    "cache/",
    "__pycache__/",
)


def git_files():
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return [item for item in result.stdout.decode("utf-8").split("\0") if item]


def is_forbidden(path):
    name = Path(path).name.lower()
    lowered = path.replace("\\", "/").lower()
    if name in FORBIDDEN_NAMES or name.startswith(".env."):
        return "credential or environment file"
    if any(part in name for part in FORBIDDEN_NAME_PARTS):
        return "credential-like filename"
    if any(part in lowered for part in FORBIDDEN_DIR_PARTS):
        return "generated data directory"
    if lowered.endswith(FORBIDDEN_SUFFIXES):
        return "prohibited generated artifact"
    return None


def main():
    failures = []
    files = git_files()
    if not files:
        print("no Git-tracked files", file=sys.stderr)
        return 1
    for relpath in files:
        reason = is_forbidden(relpath)
        if reason:
            failures.append(f"{relpath}: {reason}")
            continue
        size = Path(relpath).stat().st_size
        if size > MAX_BYTES:
            failures.append(f"{relpath}: {size} bytes exceeds 1 MiB")
    if failures:
        print("prohibited Git content:", file=sys.stderr)
        for item in failures:
            print(f"  {item}", file=sys.stderr)
        return 1
    print(f"content-guard passed for {len(files)} tracked files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())