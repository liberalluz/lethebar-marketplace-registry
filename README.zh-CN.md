<!-- translation-of: README.md -->
# Lethebar 市场索引仓

[English](README.md) · 简体中文

> Lethebar 市场背后的索引：有什么、一个名字和一个版本指向哪份字节、审过什么。它从不存包。

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

## 状态

**还没有收录任何包。** schema、校验器与审查笔记已经就位；第一批记录随第一个 pull request 进来。一条收录就是 `index.json` 里一行 JSON，加 `reviews/` 下一份笔记；zip 留在作者自己的 release 页。

## 这里有什么

| 路径 | 回答什么 |
| --- | --- |
| `index.json` | 有什么，以及一个 `(namespace, id, version)` 指向哪份 zip |
| `schema/index.schema.json` | 一条记录有哪些字段、哪些值允许 |
| `tools/validate.py` | 索引是否符合 schema；`--self-test` 检查检查器本身 |
| `reviews/` | 审查者按 kind 看了什么 |
| `docs/decisions/` | 为什么索引是这个形状 |

## 跑它

```bash
python tools/validate.py --self-test
python tools/validate.py index.json
```

## 一个包怎么进来

1. 作者在自己的 release 页发布 zip。
2. 一个 pull request 往 `index.json` 追加一条记录，并在 `reviews/<namespace>/<id>/<version>.md` 下留一份笔记。
3. CI 跑 schema 与校验器；审查者按 kind 读笔记。

身份是 `(namespace, id, version)`：`namespace` 是作者标识，`id` 是包自己的 id，保持扁平。版本永不改写；下架把 `status` 设成 `withdrawn`，记录保留。见 `docs/decisions/0001-marketplace-trust.md`。

## 许可

本仓自己的文件是 Apache-2.0。它收录的包各自保留自己的许可。
