"""Check release file hashes; --update intentionally replaces SHA256SUMS.txt."""

import argparse
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".venv", ".venv-win", "runs"}


def package_files():
    for path in sorted(ROOT.rglob("*")):
        relative = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in relative.parts) or path.is_symlink():
            continue
        if path.is_file() and path.name != "SHA256SUMS.txt":
            if path.name.startswith(".env") or path.suffix in {".pyc", ".db"}:
                raise ValueError(f"Unexpected local file: {relative.as_posix()}")
            if path.name == ".DS_Store" or path.name.startswith((".~", "~$")):
                raise ValueError(f"Editor file must not be published: {relative.as_posix()}")
            yield path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    actual = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in package_files()}
    checksums = ROOT / "SHA256SUMS.txt"
    if args.update:
        checksums.write_text("".join(f"{digest}  {name}\n" for name, digest in actual.items()), encoding="utf-8")
    expected = {}
    for line in checksums.read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        if name in expected:
            raise ValueError(f"Duplicate checksum entry: {name}")
        expected[name] = digest
    mismatches = sorted(name for name in actual.keys() | expected.keys() if actual.get(name) != expected.get(name))
    if mismatches:
        for name in mismatches:
            print(f"MISMATCH: {name}")
        return 1
    print(f"PASS: {len(actual)} release files match SHA256SUMS.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
