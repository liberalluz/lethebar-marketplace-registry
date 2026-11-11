<!-- translation-of: STD.md -->
# 软件测试说明 - 市场索引仓

每个用例都从已提交的 `index.json` 出发，只改一处。命令在仓库根目录运行。

## TC-INDEX-001 - schemaVersion 必须是 1

覆盖：`REQ-001`。
夹具：`{"schemaVersion": 2, "packages": []}`。
步骤：`python tools/validate.py fixture.json`。
出口：`[index] schemaVersion must be 1`，退出 1。

## TC-INDEX-002 - 必填字段真的必填

覆盖：`REQ-002`。
夹具：一条删掉 `sha256` 的记录。
步骤：`python tools/validate.py fixture.json`。
出口：报错点名 `packages[0]: missing sha256`，退出 1。

## TC-INDEX-003 - 包 id 保持扁平

覆盖：`REQ-003`。
夹具：`id` 设为 `liberalluz.example`。
步骤：`python tools/validate.py fixture.json`。
出口：报错点名 `id is not a lowercase slug`，退出 1。

## TC-INDEX-004 - 版本是三个数字

覆盖：`REQ-004`。
夹具：`version` 设为 `1.0`。
步骤：`python tools/validate.py fixture.json`。
出口：报错点名 `version is not major.minor.patch`，退出 1。

## TC-INDEX-005 - 引擎范围不能为空

覆盖：`REQ-005`。
夹具：`engine` 设为 `""`。
步骤：`python tools/validate.py fixture.json`。
出口：报错点名 `engine range is empty`，退出 1。

## TC-INDEX-006 - 能力必须带主版本

覆盖：`REQ-006`。
夹具：`capabilities` 设为 `["text"]`。
步骤：`python tools/validate.py fixture.json`。
出口：报错点名 `capabilities must be name@major`，退出 1。

## TC-INDEX-007 - 许可在白名单上

覆盖：`REQ-007`。
夹具：`license` 设为 `Proprietary`。
步骤：`python tools/validate.py fixture.json`。
出口：报错点名 `license is not on the SPDX whitelist`，退出 1。

## TC-INDEX-008 - kind 与 layer 一致

覆盖：`REQ-008`。
夹具：`kind` 设为 `layer` 并删掉 `layer`。
步骤：`python tools/validate.py fixture.json`。
出口：报错点名 `a layer must name a layer dimension`，退出 1。

## TC-INDEX-009 - 身份唯一

覆盖：`REQ-009`。
夹具：同一条记录出现两次。
步骤：`python tools/validate.py fixture.json`。
出口：报错点名 `duplicate ...`，退出 1。

## TC-INDEX-010 - 一份摘要对应一个 zip

覆盖：`REQ-010`。
夹具：两条记录共用同一 `sha256`。
步骤：`python tools/validate.py fixture.json`。
出口：报错点名 `sha256 already used by another record`，退出 1。

## TC-INDEX-011 - status 只有两个值

覆盖：`REQ-011`。
夹具：`status` 设为 `draft`。
步骤：`python tools/validate.py fixture.json`。
出口：报错点名 `status must be published or withdrawn`，退出 1。

## TC-INDEX-012 - 校验器能独立运行

覆盖：`REQ-012`。
夹具：已提交的 `index.json`，再用 `TC-INDEX-001` 的夹具。
步骤：`python tools/validate.py --self-test`，再 `python tools/validate.py index.json`，再 `python tools/validate.py fixture.json`。
出口：自测 0，干净索引 0，坏夹具 1。
