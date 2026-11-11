# Lethebar marketplace registry

English · [简体中文](README.zh-CN.md)

> The index behind the Lethebar marketplace: what exists, which bytes a name and a version mean, and what was reviewed. It never stores a package.

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

## Status

**No package is listed yet.** The schema, the validator and the review notes are in place; the first records arrive with the first pull request. A listing is one JSON record in `index.json` plus one note under `reviews/`; the zip stays on the author's release page.

## What is here

| Path | Answers |
| --- | --- |
| `index.json` | What exists, and which zip a `(namespace, id, version)` means |
| `schema/index.schema.json` | Which fields a record has, and which values are allowed |
| `tools/validate.py` | Whether the index obeys the schema; `--self-test` checks the checks |
| `reviews/` | What a reviewer looked at, by kind |
| `docs/decisions/` | Why the registry is shaped this way |

## Run it

```bash
python tools/validate.py --self-test
python tools/validate.py index.json
```

## How a package gets in

1. The author publishes the zip on their own release page.
2. A pull request appends one record to `index.json` and one note under `reviews/<namespace>/<id>/<version>.md`.
3. CI runs the schema and the validator; a reviewer reads the note by kind.

Identity is `(namespace, id, version)`: `namespace` is the author's handle, `id` is the package's own id and stays flat. A version is never edited; a withdrawal sets `status: withdrawn` and keeps the record. See `docs/decisions/0001-marketplace-trust.md`.

## Licence

The registry's own files are Apache-2.0. The packages it lists keep their own licences.
