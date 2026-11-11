# Software design - the marketplace registry

## 1. What it is

A JSON file, a schema, a validator and one review note per record. There is no
server, no database and no upload; the site is built from a pinned commit.

## 2. Data model

| Field | Type | Rule |
| --- | --- | --- |
| `schemaVersion` | integer | exactly `1` |
| `packages` | array | one record per listed `(namespace, id, version)` |
| `namespace` | string | lowercase slug, the author's handle |
| `id` | string | lowercase slug, the package's own id, flat |
| `version` | string | `major.minor.patch` |
| `sha256` | string | 64 hex, the zip's digest |
| `specVersion` | string | `major.minor.patch` |
| `engine` | string | a range such as `>=4.7.0 <5.0.0` |
| `capabilities` | array | `name@major` strings |
| `author` | string | who published it |
| `license` | string | SPDX id on the whitelist |
| `homepage` | string | where a player reads more |
| `tags` | array | free labels |
| `collection` | string | optional shelf grouping |
| `kind` | string | `bundle` or `layer`, optional |
| `layer` | string | one of the six dimensions, only for a layer |
| `publishedAt` | string | RFC 3339 timestamp |
| `status` | string | `published` or `withdrawn` |

## 3. Validation pipeline

1. `schema/index.schema.json` states the shape and the value sets.
2. `tools/validate.py` adds what a schema cannot express: the SPDX whitelist,
   kind and layer agreement, unique identity and unique digest.
3. CI runs the validator on every pull request that touches `index.json`.

A record that fails either layer is not merged; the index is never partially
valid.

## 4. Mapping

| REQ | Landing |
| --- | --- |
| `REQ-001` | `index.json` top level; `schema/index.schema.json` |
| `REQ-002` | `$defs.record.required`; `tools/validate.py` `REQUIRED` |
| `REQ-003` | `$defs.record` `pattern`; `tools/validate.py` `SLUG` |
| `REQ-004` | `$defs.record` `pattern`; `tools/validate.py` `SEMVER` |
| `REQ-005` | `$defs.record.engine` `minLength`; `tools/validate.py` empty check |
| `REQ-006` | `$defs.record.capabilities` `pattern`; `tools/validate.py` `CAP` |
| `REQ-007` | `tools/validate.py` `LICENSES` |
| `REQ-008` | `schema` `allOf`; `tools/validate.py` `KINDS` and `LAYERS` |
| `REQ-009` | `tools/validate.py` `seen` set |
| `REQ-010` | `$defs.record.sha256` `pattern`; `tools/validate.py` `SHAS` set |
| `REQ-011` | `$defs.record.status` `enum`; `tools/validate.py` `STATUS` |
| `REQ-012` | `tools/validate.py` `main()` and `--self-test` |

## 5. Out of scope

The site (`M03`), the review conversation and the engine's install path are not
designed here. The registry links to a release; it never serves bytes.
