<!-- translation-of: SRS.md -->
# 软件需求 - 市场索引仓

索引仓替引擎回答一个问题：`(namespace, id, version)` 指的是哪份字节。以下需求是这个仓做出并检查的承诺；站点、审查对话和引擎不在其中。

| ID | 需求 | 理由 |
| --- | --- | --- |
| REQ-001 | 索引是一个 JSON 对象，`schemaVersion` 固定为 `1`，`packages` 是数组。 | 读者解析一个文件，不是一个目录。 |
| REQ-002 | 每条记录都带 `namespace`、`id`、`version`、`sha256`、`specVersion`、`engine`、`capabilities`、`author`、`license`、`homepage`、`tags`、`publishedAt` 和 `status`。 | 记录先完整，再上架。 |
| REQ-003 | `namespace` 与 `id` 匹配 `^[a-z0-9-]+$`；`id` 是扁平的，永不含点。 | 引擎把扁平 id 当存档键。 |
| REQ-004 | `version` 与 `specVersion` 是 `major.minor.patch`。 | 版本要过引擎的范围检查。 |
| REQ-005 | `engine` 是非空的范围字符串。 | 包要说明它能在哪些引擎构建上跑。 |
| REQ-006 | `capabilities` 是 `name@major` 的列表。 | 引擎拒绝声明了它不提供的能力的包。 |
| REQ-007 | `license` 在本仓的 SPDX 白名单上。 | 上架条目带一个玩家能读的许可。 |
| REQ-008 | `kind` 是 `bundle` 或 `layer`；层恰好点名六个维度之一，非层不点名任何维度。 | 补丁要说明它改一局的哪一部分。 |
| REQ-009 | `(namespace, id, version)` 至多出现一次。 | 版本不可变且无歧义。 |
| REQ-010 | `sha256` 是 64 个小写十六进制字符，且全索引唯一。 | 两条记录不会指向同一份字节。 |
| REQ-011 | `status` 是 `published` 或 `withdrawn`；撤下的记录保留。 | 撤下是事实，不是删除。 |
| REQ-012 | 校验器离线运行、不依赖第三方包，索引违规时以非零码退出。 | 拉取请求由本仓检查，不由某个服务检查。 |
