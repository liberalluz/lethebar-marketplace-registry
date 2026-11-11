#!/usr/bin/env python3
"""Withdraw a record without deleting it (B3).

A withdrawal flips `status` to `withdrawn` and appends a dated note under
`reviews/`. The record, its hash and its history stay in the file: a site can
still say "this version existed and was withdrawn".
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import validate  # noqa: E402


def find(index: dict, namespace: str, package_id: str, version: str) -> dict | None:
    for record in index.get("packages", []):
        if (
            record.get("namespace") == namespace
            and record.get("id") == package_id
            and record.get("version") == version
        ):
            return record
    return None


def note_path(root: Path, namespace: str, package_id: str, version: str) -> Path:
    return root / "reviews" / namespace / package_id / f"{version}.md"


def withdrawal_note(namespace: str, package_id: str, version: str, reason: str, date: str, by: str) -> str:
    return (
        f"\n## Withdrawal\n\n"
        f"- date: {date}\n"
        f"- by: {by}\n"
        f"- reason: {reason}\n"
        f"- status: withdrawn\n"
    )


def withdraw(index: dict, namespace: str, package_id: str, version: str) -> dict:
    record = find(index, namespace, package_id, version)
    if record is None:
        raise SystemExit(f"no record {namespace}/{package_id}@{version}")
    if record.get("status") != "published":
        raise SystemExit(f"{namespace}/{package_id}@{version} is already {record.get('status')}")
    record["status"] = "withdrawn"
    return record


def self_test() -> int:
    index = {
        "schemaVersion": 1,
        "generatedAt": "2026-11-11T00:00:00Z",
        "packages": [{
            "namespace": "liberalluz", "id": "example", "version": "0.1.0",
            "sha256": "a" * 64, "specVersion": "2.0.0",
            "engine": ">=4.7.0 <5.0.0", "capabilities": ["text@1"],
            "author": "liberalluz", "license": "Apache-2.0",
            "homepage": "https://example.invalid", "tags": ["demo"],
            "publishedAt": "2026-11-11T00:00:00Z", "status": "published",
            "kind": "bundle",
        }],
    }
    withdraw(index, "liberalluz", "example", "0.1.0")
    cases = [
        ("the record is still there", len(index["packages"]) == 1),
        ("its status is withdrawn", index["packages"][0]["status"] == "withdrawn"),
        ("a withdrawn record still validates", validate.check(index) == []),
    ]
    failures = 0
    for name, ok in cases:
        print(("ok   " if ok else "FAIL ") + name)
        failures += 0 if ok else 1
    try:
        withdraw(index, "liberalluz", "example", "0.1.0")
    except SystemExit:
        print("ok   a second withdrawal is refused")
    else:
        print("FAIL a second withdrawal is refused")
        failures += 1
    return 1 if failures else 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--withdraw", metavar="NAMESPACE/ID@VERSION")
    parser.add_argument("--reason")
    parser.add_argument("--date", default="2026-11-11")
    parser.add_argument("--by", default="liberalluz")
    parser.add_argument("--root", default=".")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv[1:])
    if not args.withdraw:
        parser.error("--self-test or --withdraw is required")
    if not args.reason:
        parser.error("--reason is required with --withdraw")
    target = args.withdraw
    namespace, _, rest = target.partition("/")
    package_id, _, version = rest.partition("@")
    root = Path(args.root)
    index_path = root / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    withdraw(index, namespace, package_id, version)
    note = withdrawal_note(namespace, package_id, version, args.reason, args.date, args.by)
    if not args.apply:
        print(f"would withdraw {namespace}/{package_id}@{version}")
        print(note)
        return 0
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    path = note_path(root, namespace, package_id, version)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(note)
    print(f"withdrew {namespace}/{package_id}@{version}; note in {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
