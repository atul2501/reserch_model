"""Fail if a tracked file contains something shaped like a real credential.

Usage: python -m scripts.secret_scan
Scans tracked files AND untracked-but-not-ignored ones (`git ls-files -co --exclude-standard`), so a new file is checked
BEFORE it is ever committed; prints file:line and
the rule name only, NEVER the matched value. Exit code 1 on any finding.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

PLACEHOLDER = re.compile(r"(?i)^(|change_?me|your[-_a-z0-9]*|xxx+|example|placeholder|<.*>|\$\{.*\}|\*+|redacted|secret|k\d*|p|pass|password|user|postgres|ci_only_[a-z_]+)$")

RULES: list[tuple[str, re.Pattern[str]]] = [
    ("hex-private-key", re.compile(r"\b0x[a-fA-F0-9]{64}\b")),
    ("aws-access-key-id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("pem-private-key", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----")),
]
ASSIGNMENT = re.compile(
    r"(?im)^\s*(?:export\s+)?(HYPERLIQUID_PRIVATE_KEY|OLLAMA_API_KEYS?|AWS_SECRET_ACCESS_KEY|JWT_SECRET|API_SECRET|DB_PASSWORD|POSTGRES_PASSWORD)\s*=\s*(.*?)\s*$"
)
DB_URL = re.compile(r"(?i)\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:([^\s@/]+)@")

SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".db", ".sqlite", ".pyc", ".woff", ".woff2"}


def _is_placeholder(value: str) -> bool:
    return bool(PLACEHOLDER.match(value.strip().strip("\"'")))


def scan_text(name: str, text: str) -> list[tuple[str, int, str]]:
    findings: list[tuple[str, int, str]] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for rule, pattern in RULES:
            if pattern.search(line):
                findings.append((name, lineno, rule))
        m = ASSIGNMENT.match(line) if not name.endswith(".py") else None  # env-style files only
        if m and not _is_placeholder(m.group(2)):
            findings.append((name, lineno, f"secret-assignment:{m.group(1)}"))
        for m in DB_URL.finditer(line):
            if not _is_placeholder(m.group(1)):
                findings.append((name, lineno, "db-url-password"))
    return findings


def tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z", "-co", "--exclude-standard"], cwd=REPO_ROOT, capture_output=True, check=True).stdout
    return [REPO_ROOT / p for p in out.decode().split("\0") if p]


def main(argv: list[str]) -> int:
    findings: list[tuple[str, int, str]] = []
    for path in tracked_files():
        if path.suffix.lower() in SKIP_SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        findings.extend(scan_text(str(path.relative_to(REPO_ROOT)), text))
    for name, lineno, rule in findings:
        print(f"{name}:{lineno}: {rule}")
    if findings:
        print(f"secret scan FAILED: {len(findings)} finding(s) (values intentionally not printed)", file=sys.stderr)
        return 1
    print("secret scan ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
