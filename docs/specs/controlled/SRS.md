# Software requirements - the marketplace registry

The registry answers one question for an engine: which bytes does a
`(namespace, id, version)` mean. These requirements are the promise this
repository makes and checks. The site, the review conversation and the engine
are outside them.

| ID | Requirement | Reason |
| --- | --- | --- |
| REQ-001 | The index is one JSON object with `schemaVersion` fixed at `1` and a `packages` array. | A reader parses one file, not a directory. |
| REQ-002 | Every record carries `namespace`, `id`, `version`, `sha256`, `specVersion`, `engine`, `capabilities`, `author`, `license`, `homepage`, `tags`, `publishedAt` and `status`. | A record is complete before it is listed. |
| REQ-003 | `namespace` and `id` match `^[a-z0-9-]+$`; `id` is flat and never contains a dot. | The engine accepts a flat id as a save key. |
| REQ-004 | `version` and `specVersion` are `major.minor.patch`. | A version is read by the engine's range check. |
| REQ-005 | `engine` is a non-empty range string. | A package names the engine builds it runs on. |
| REQ-006 | `capabilities` is a list of `name@major`. | The engine refuses a package whose capability it does not provide. |
| REQ-007 | `license` is on the registry's SPDX whitelist. | A listing carries a licence a player can read. |
| REQ-008 | `kind` is `bundle` or `layer`; a layer names exactly one of the six dimensions, and a record that is not a layer names none. | A patch says what part of a run it changes. |
| REQ-009 | `(namespace, id, version)` appears at most once. | A version is immutable and unambiguous. |
| REQ-010 | `sha256` is 64 lowercase hex characters and unique across the index. | Two records never nominate the same bytes. |
| REQ-011 | `status` is `published` or `withdrawn`; a withdrawn record is kept. | Withdrawal is a fact, not a deletion. |
| REQ-012 | The validator runs offline with no third-party package and exits non-zero when the index breaks a rule. | A pull request is checked by the repository, not by a service. |
