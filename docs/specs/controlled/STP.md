# Software test plan - the marketplace registry

| ID | Covers | Level | Exit |
| --- | --- | --- | --- |
| `TC-INDEX-001` | `REQ-001` | validator | `schemaVersion` other than 1 is refused |
| `TC-INDEX-002` | `REQ-002` | validator | a record missing `sha256` is refused |
| `TC-INDEX-003` | `REQ-003` | validator | `liberalluz.example` is refused; `example` passes |
| `TC-INDEX-004` | `REQ-004` | validator | `1.0` is refused; `1.0.0` passes |
| `TC-INDEX-005` | `REQ-005` | validator | an empty `engine` is refused |
| `TC-INDEX-006` | `REQ-006` | validator | `text` is refused; `text@1` passes |
| `TC-INDEX-007` | `REQ-007` | validator | `Proprietary` is refused; `Apache-2.0` passes |
| `TC-INDEX-008` | `REQ-008` | validator | `kind: layer` without `layer` is refused; `layer` on a bundle is refused |
| `TC-INDEX-009` | `REQ-009` | validator | the same `(namespace, id, version)` twice is refused |
| `TC-INDEX-010` | `REQ-010` | validator | a 63-character digest is refused; a reused digest is refused |
| `TC-INDEX-011` | `REQ-011` | validator | `status: draft` is refused; `withdrawn` passes |
| `TC-INDEX-012` | `REQ-012` | CLI | `--self-test` exits 0; a broken index exits 1 |
