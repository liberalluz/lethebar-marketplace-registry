<!-- translation-of: STP.md -->
# 软件测试计划 - 市场索引仓

| ID | 覆盖 | 层级 | 出口 |
| --- | --- | --- | --- |
| `TC-INDEX-001` | `REQ-001` | 校验器 | `schemaVersion` 不是 1 被拒 |
| `TC-INDEX-002` | `REQ-002` | 校验器 | 缺 `sha256` 的记录被拒 |
| `TC-INDEX-003` | `REQ-003` | 校验器 | `liberalluz.example` 被拒；`example` 通过 |
| `TC-INDEX-004` | `REQ-004` | 校验器 | `1.0` 被拒；`1.0.0` 通过 |
| `TC-INDEX-005` | `REQ-005` | 校验器 | 空 `engine` 被拒 |
| `TC-INDEX-006` | `REQ-006` | 校验器 | `text` 被拒；`text@1` 通过 |
| `TC-INDEX-007` | `REQ-007` | 校验器 | `Proprietary` 被拒；`Apache-2.0` 通过 |
| `TC-INDEX-008` | `REQ-008` | 校验器 | `kind: layer` 缺 `layer` 被拒；bundle 带 `layer` 被拒 |
| `TC-INDEX-009` | `REQ-009` | 校验器 | 同一 `(namespace, id, version)` 两次被拒 |
| `TC-INDEX-010` | `REQ-010` | 校验器 | 63 位摘要被拒；复用摘要被拒 |
| `TC-INDEX-011` | `REQ-011` | 校验器 | `status: draft` 被拒；`withdrawn` 通过 |
| `TC-INDEX-012` | `REQ-012` | 命令行 | `--self-test` 退出 0；坏索引退出 1 |
