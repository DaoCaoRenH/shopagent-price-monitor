"""Check the files selected for publication without printing sensitive matches."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_ROOTS = {".venv", ".shopagent", "secrets", "local-data", "runs", "resume-runs", "manifests"}
PATTERNS = {
    "GitHub credential": re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"),
    "provider credential": re.compile(r"(?:sk-(?:proj-)?[A-Za-z0-9_-]{32,}|AIza[A-Za-z0-9_-]{30,})"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "private network": re.compile(r"\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.10\.10\.\d{1,3}|gpu\d{3})\b"),
    "machine-specific path": re.compile(r"[A-Za-z]:[/\\](?:Users|codex)[/\\]", re.IGNORECASE),
}


def credential_field(value) -> bool:
    if isinstance(value, dict):
        return any(
            (key.casefold() in {"api_key", "access_token", "password"} and bool(item)) or credential_field(item)
            for key, item in value.items()
        )
    return isinstance(value, list) and any(credential_field(item) for item in value)


def main() -> int:
    output = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    filenames = [name for name in output.decode("utf-8").split("\0") if name]
    if not filenames:
        print("No tracked release files. Stage the reviewed public files first.")
        return 1
    problems = []
    total = 0
    for filename in filenames:
        path = ROOT / filename
        parts = Path(filename).parts
        if parts[0] in FORBIDDEN_ROOTS or path.suffix in {".db", ".sqlite", ".sqlite3", ".log", ".pid", ".key", ".pem"}:
            problems.append((filename, "local state or credentials"))
        if path.name == "items_eval_train.json" or path.name.startswith(".env"):
            problems.append((filename, "private dataset or environment file"))
        content = path.read_bytes()
        total += len(content)
        if len(content) > 5_000_000:
            problems.append((filename, "unexpected large file"))
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            problems.append((filename, "unexpected binary file"))
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                problems.append((filename, label))
        if path.suffix == ".json" and credential_field(json.loads(text)):
            problems.append((filename, "non-empty credential field"))
    if problems:
        for filename, label in problems:
            print(f"{filename}: {label}")
        return 1
    print(f"Release file check passed: {len(filenames)} files, {total:,} bytes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
