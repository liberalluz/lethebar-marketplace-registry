# Software test descriptions - the marketplace registry

Every case starts from `index.json` as committed and changes one thing. The
commands run from the repository root.

## TC-INDEX-001 - schemaVersion must be 1

Covers: `REQ-001`.
Fixture: `{"schemaVersion": 2, "packages": []}`.
Steps: `python tools/validate.py fixture.json`.
Exit: `[index] schemaVersion must be 1`, exit 1.

## TC-INDEX-002 - a required field is required

Covers: `REQ-002`.
Fixture: one record with `sha256` removed.
Steps: `python tools/validate.py fixture.json`.
Exit: an error naming `packages[0]: missing sha256`, exit 1.

## TC-INDEX-003 - the package id stays flat

Covers: `REQ-003`.
Fixture: `id` set to `liberalluz.example`.
Steps: `python tools/validate.py fixture.json`.
Exit: an error naming `id is not a lowercase slug`, exit 1.

## TC-INDEX-004 - versions are three numbers

Covers: `REQ-004`.
Fixture: `version` set to `1.0`.
Steps: `python tools/validate.py fixture.json`.
Exit: an error naming `version is not major.minor.patch`, exit 1.

## TC-INDEX-005 - an engine range is not empty

Covers: `REQ-005`.
Fixture: `engine` set to `""`.
Steps: `python tools/validate.py fixture.json`.
Exit: an error naming `engine range is empty`, exit 1.

## TC-INDEX-006 - a capability names a major

Covers: `REQ-006`.
Fixture: `capabilities` set to `["text"]`.
Steps: `python tools/validate.py fixture.json`.
Exit: an error naming `capabilities must be name@major`, exit 1.

## TC-INDEX-007 - a licence is on the whitelist

Covers: `REQ-007`.
Fixture: `license` set to `Proprietary`.
Steps: `python tools/validate.py fixture.json`.
Exit: an error naming `license is not on the SPDX whitelist`, exit 1.

## TC-INDEX-008 - kind and layer agree

Covers: `REQ-008`.
Fixture: `kind` set to `layer` with `layer` removed.
Steps: `python tools/validate.py fixture.json`.
Exit: an error naming `a layer must name a layer dimension`, exit 1.

## TC-INDEX-009 - identity is unique

Covers: `REQ-009`.
Fixture: the same record twice.
Steps: `python tools/validate.py fixture.json`.
Exit: an error naming `duplicate ...`, exit 1.

## TC-INDEX-010 - a digest is one zip

Covers: `REQ-010`.
Fixture: two records with the same `sha256`.
Steps: `python tools/validate.py fixture.json`.
Exit: an error naming `sha256 already used by another record`, exit 1.

## TC-INDEX-011 - status has two values

Covers: `REQ-011`.
Fixture: `status` set to `draft`.
Steps: `python tools/validate.py fixture.json`.
Exit: an error naming `status must be published or withdrawn`, exit 1.

## TC-INDEX-012 - the validator runs by itself

Covers: `REQ-012`.
Fixture: `index.json` as committed, then the fixture from `TC-INDEX-001`.
Steps: `python tools/validate.py --self-test`, then `python tools/validate.py index.json`, then `python tools/validate.py fixture.json`.
Exit: self-test 0, clean index 0, broken fixture 1.
