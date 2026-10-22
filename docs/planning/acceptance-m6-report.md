# M6 验收报告（自动生成）

- 生成时间：2026-10-22T11:56:38+0000
- 分支 / 提交：feat/req-202610-0959-m6-acceptance / 8760b26
- 运行环境：Linux-6.8.0-138-generic-x86_64-with-glibc2.39 · Python 3.12.3
- 验收方式：临时 SQLite + 真实 uvicorn + API 契约检查 + edge / admin 资产静态检查
- 判定口径：PASS 通过 · FAIL 行为错误 · GAP 未交付缺口（不计入通过率）

## 检查结果

| # | 检查 | 结果 | 说明 | 耗时 |
| --- | --- | --- | --- | --- |
| M6-S01 | M6-04 技术栈图谱资产 | PASS | edge 聚合 + admin 页面 + 单测齐全 | 0.7ms |
| M6-S02 | M6-08 知识库导出资产 | PASS | edge 导出 + admin 页面 + 格式规范齐全 | 0.9ms |
| M6-S03 | M6 前端页面齐全 | PASS | 重复检测 / License / 依赖分析 / 仓库健康度页面齐全 | 0.3ms |
| M6-09-GAP | 多轮问答式检索（平台 pending） | GAP | feat/req-202610-0956-conversational-search 未合并，需该需求交付后补充验收 | 0.0ms |
| M6-10-GAP | 检索体验精修（平台 pending） | GAP | feat/req-202610-0957-search-ux 未合并，需该需求交付后补充验收 | 0.0ms |
| M6-11-GAP | 主题聚类与自动标签（平台 pending） | GAP | feat/req-202610-0958-theme-clustering 未合并，需该需求交付后补充验收 | 0.0ms |
| M6-A01 | M6-01 FTS5 虚表与触发器 | PASS | 3 个触发器；FTS 文档 3 | 1.8ms |
| M6-A02 | M6-01 中文短词检索（LIKE 回退） | PASS | mode=like count=2 | 64.0ms |
| M6-A03 | M6-01 英文长词 FTS + 索引状态 | PASS | count=2 docs=3 | 20.9ms |
| M6-A04 | M6-01 索引重建 | PASS | rebuilt=3 | 22.5ms |
| M6-B01 | M6-02 相似推荐近邻 | PASS | top1=acme/payment-kit-js score=0.988488 | 13.9ms |
| M6-B02 | M6-02 种子缺失语义 | PASS | 404 / 409 语义正确 | 15.0ms |
| M6-C01 | M6-03 重复检测与合并建议 | PASS | clusters=1 confidence=0.8866 | 19.6ms |
| M6-D01 | M6-05 健康度列表与汇总 | PASS | total=4 statuses=['active', 'archived', 'stale'] | 10.8ms |
| M6-D02 | M6-05 单仓库健康度 | PASS | status=active score=100 | 6.0ms |
| M6-D03 | M6-05 健康度刷新入队 | PASS | taskId=ccfe2892-b085-43f4-9ea3-5febd15fc202 | 180.9ms |
| M6-E01 | M6-06 License 目录 | PASS | categories=6 licenses=16 | 4.2ms |
| M6-E02 | M6-06 License 汇总与风险 | PASS | total=4 high=1 | 9.7ms |
| M6-E03 | M6-06 单仓库 License 提示 | PASS | MIT / permissive / low | 7.3ms |
| M6-F01 | M6-07 依赖分析聚合 | PASS | repos=2 rows=6 | 15.0ms |
| M6-F02 | M6-07 依赖扫描接口 | PASS | status=ok scanned=0 | 12.7ms |

## 汇总

- PASS：18
- FAIL：0
- GAP：3
- 结论：M6-01~08 已交付能力全部通过；M6-09~11 平台状态仍为 pending，本轮判定为部分验收（有条件通过）
