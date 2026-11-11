<!-- translation-of: SDD.md -->
# 软件设计 - 市场索引仓

## 1. 它是什么

一个 JSON 文件、一份 schema、一个校验器，以及每条记录一份审查笔记。没有服务器、没有数据库、没有上传；站点从固定提交构建。

## 2. 数据模型

| 字段 | 类型 | 规则 |
| --- | --- | --- |
| `schemaVersion` | 整数 | 恰好为 `1` |
| `packages` | 数组 | 每个上架的 `(namespace, id, version)` 一条记录 |
| `namespace` | 字符串 | 小写 slug，作者句柄 |
| `id` | 字符串 | 小写 slug，包自己的 id，扁平 |
| `version` | 字符串 | `major.minor.patch` |
| `sha256` | 字符串 | 64 位十六进制，zip 的摘要 |
| `specVersion` | 字符串 | `major.minor.patch` |
| `engine` | 字符串 | 形如 `>=4.7.0 <5.0.0` 的范围 |
| `capabilities` | 数组 | `name@major` 字符串 |
| `author` | 字符串 | 发布者 |
| `license` | 字符串 | 白名单上的 SPDX id |
| `homepage` | 字符串 | 玩家读更多信息的地方 |
| `tags` | 数组 | 自由标签 |
| `collection` | 字符串 | 可选的货架分组 |
| `kind` | 字符串 | `bundle` 或 `layer`，可选 |
| `layer` | 字符串 | 六个维度之一，仅层使用 |
| `publishedAt` | 字符串 | RFC 3339 时间戳 |
| `status` | 字符串 | `published` 或 `withdrawn` |

## 3. 校验流水线

1. `schema/index.schema.json` 说明形状与取值集合。
2. `tools/validate.py` 补上 schema 表达不了的规则：SPDX 白名单、kind 与 layer 一致、身份唯一、摘要唯一。
3. CI 在每个改到 `index.json` 的拉取请求上运行校验器。

任一层失败就不合并；索引不会处于“部分有效”的状态。

## 4. 映射

| REQ | 落点 |
| --- | --- |
| `REQ-001` | `index.json` 顶层；`schema/index.schema.json` |
| `REQ-002` | `$defs.record.required`；`tools/validate.py` 的 `REQUIRED` |
| `REQ-003` | `$defs.record` 的 `pattern`；`tools/validate.py` 的 `SLUG` |
| `REQ-004` | `$defs.record` 的 `pattern`；`tools/validate.py` 的 `SEMVER` |
| `REQ-005` | `$defs.record.engine` 的 `minLength`；`tools/validate.py` 的空值检查 |
| `REQ-006` | `$defs.record.capabilities` 的 `pattern`；`tools/validate.py` 的 `CAP` |
| `REQ-007` | `tools/validate.py` 的 `LICENSES` |
| `REQ-008` | `schema` 的 `allOf`；`tools/validate.py` 的 `KINDS` 与 `LAYERS` |
| `REQ-009` | `tools/validate.py` 的 `seen` 集合 |
| `REQ-010` | `$defs.record.sha256` 的 `pattern`；`tools/validate.py` 的 `SHAS` 集合 |
| `REQ-011` | `$defs.record.status` 的 `enum`；`tools/validate.py` 的 `STATUS` |
| `REQ-012` | `tools/validate.py` 的 `main()` 与 `--self-test` |

## 5. 不在范围内

站点（`M03`）、审查对话和引擎的安装路径不在这里设计。索引仓链接到发布页；它从不提供字节。
