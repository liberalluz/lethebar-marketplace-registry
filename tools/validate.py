#!/usr/bin/env python3
"""Validate the registry index without third-party packages."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
SLUG = re.compile(r"^[a-z0-9-]+$")
SHA = re.compile(r"^[0-9a-f]{64}$")
CAP = re.compile(r"^[a-z][a-z0-9.]*@[0-9]+$")
KINDS = {"bundle", "layer"}
LAYERS = {"profession", "genre", "mod", "content", "meta", "assets"}
STATUS = {"published", "withdrawn"}
LICENSES = {
    "Apache-2.0", "MIT", "BSD-3-Clause", "CC0-1.0", "CC-BY-4.0", "GPL-3.0-only",
}
REQUIRED = (
    "namespace", "id", "version", "sha256", "specVersion", "engine",
    "capabilities", "author", "license", "homepage", "tags",
    "publishedAt", "status",
)


def check(index: dict) -> list[str]:
    errors: list[str] = []
    if index.get("schemaVersion") != 1:
        errors.append("schemaVersion must be 1")
    packages = index.get("packages")
    if not isinstance(packages, list):
        errors.append("packages must be an array")
        return errors
    seen: set[tuple[str, str, str]] = set()
    shas: set[str] = set()
    for n, record in enumerate(packages):
        where = f"packages[{n}]"
        if not isinstance(record, dict):
            errors.append(f"{where} must be an object")
            continue
        for key in REQUIRED:
            if key not in record:
                errors.append(f"{where}: missing {key}")
        for key in ("namespace", "id"):
            if not SLUG.match(str(record.get(key, ""))):
                errors.append(f"{where}: {key} is not a lowercase slug")
        if not SEMVER.match(str(record.get("version", ""))):
            errors.append(f"{where}: version is not major.minor.patch")
        if not SHA.match(str(record.get("sha256", ""))):
            errors.append(f"{where}: sha256 is not 64 hex characters")
        if not SEMVER.match(str(record.get("specVersion", ""))):
            errors.append(f"{where}: specVersion is not major.minor.patch")
        if not record.get("engine"):
            errors.append(f"{where}: engine range is empty")
        caps = record.get("capabilities")
        if not isinstance(caps, list) or any(not CAP.match(str(c)) for c in caps):
            errors.append(f"{where}: capabilities must be name@major")
        if record.get("license") not in LICENSES:
            errors.append(f"{where}: license is not on the SPDX whitelist")
        kind = record.get("kind")
        if kind is not None and kind not in KINDS:
            errors.append(f"{where}: kind must be bundle or layer")
        if kind == "layer":
            if record.get("layer") not in LAYERS:
                errors.append(f"{where}: a layer must name a layer dimension")
        elif "layer" in record:
            errors.append(f"{where}: only a layer names a dimension")
        if record.get("status") not in STATUS:
            errors.append(f"{where}: status must be published or withdrawn")
        key = (record.get("namespace", ""), record.get("id", ""), record.get("version", ""))
        if key in seen:
            errors.append(f"{where}: duplicate {key[0]}/{key[1]}@{key[2]}")
        seen.add(key)
        sha = record.get("sha256", "")
        if sha in shas:
            errors.append(f"{where}: sha256 already used by another record")
        shas.add(sha)
    return errors


def self_test() -> int:
    good = {
        "schemaVersion": 1,
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
    cases = [
        ("a clean index has no errors", check(good), []),
        ("a namespaced id is refused", check({**good, "packages": [{**good["packages"][0], "id": "liberalluz.example"}]}), None),
        ("a duplicate version is refused", check({**good, "packages": good["packages"] * 2}), None),
    ]
    failures = 0
    for name, got, want in cases:
        ok = (got == want) if want is not None else bool(got)
        print(("ok   " if ok else "FAIL ") + name)
        failures += 0 if ok else 1
    return 1 if failures else 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    target = Path(argv[1] if len(argv) > 1 else "index.json")
    try:
        index = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[index] cannot read {target}: {exc}")
        return 2
    errors = check(index)
    for error in errors:
        print(f"[index] {error}")
    print(f"[index] {len(index.get('packages', []))} record(s), {len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
