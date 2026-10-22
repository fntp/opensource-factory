# M2 验收报告（自动生成）

- 生成时间：2026-10-22T06:31:14.466Z
- 分支 / 提交：feat/req-202610-0918-m2-acceptance / 0d3e6bd
- 运行环境：linux x64 · Node v22.23.1
- 数据规模：6 个热榜仓库 / 13 条快照（5 个日期，含 2 条过期）/ 1 个测试用户
- 判定口径：PASS 通过 · GAP 能力未集成（阻塞） · FAIL 行为错误 · SKIP 跳过

## 检查结果

| # | 检查 | 结果 | 说明 | 耗时 |
| --- | --- | --- | --- | --- |
| M2-A01 | 默认返回最近一天快照（6 条，按排名升序） | PASS | 6 条 · 2026-10-22 | 64.1ms |
| M2-A02 | 按日期筛选（昨日 3 条） | PASS | 3 条 · 2026-10-21 | 34.4ms |
| M2-A03 | 按语言筛选大小写不敏感（python → 2 条） | PASS | 2 条 Python | 34.2ms |
| M2-A04 | 趋势标注 new / up / down / same 完整 | PASS | new/up/down/same 均命中 | 34.1ms |
| M2-A05 | limit 生效（limit=2）且非法日期 400 | PASS | limit=2 · 2026-02-31 → 400 | 62.3ms |
| M2-A06 | 显式日期无数据返回空数组（不静默回退） | PASS | [] | 30.4ms |
| M2-B01 | 快照日期列表倒序且带计数 | PASS | 4 个日期 · 最新 6 条 | 35.1ms |
| M2-B02 | 语言分布按日期统计 | PASS | Python 2 / TypeScript 2 / Go 1 / Rust 1 | 30.4ms |
| M2-B03 | 单仓库历史返回三点曲线（升序） | PASS | 2026-09-22 → 2026-10-21 → 2026-10-22 | 34.1ms |
| M2-C01 | 详情优先返回 README 中文摘要 | PASS | readme · 未收藏 | 39.9ms |
| M2-C02 | 摘要回退 description / tech | PASS | description → tech | 59.3ms |
| M2-C03 | 不存在的仓库详情 404 | PASS | 404 not_found | 33.2ms |
| M2-C04 | 未登录收藏返回 401 | PASS | 401 unauthorized | 14.0ms |
| M2-C05 | 一键收藏幂等写入 my_repositories | PASS | created true → false，详情 isFavorited=true | 105.3ms |
| M2-C06 | 取消收藏后详情恢复未收藏 | PASS | removed=true → 未收藏 | 73.9ms |
| M2-D01 | 摘要回写接口校验内部令牌 | PASS | 401 → 200 | 27.7ms |
| M2-D02 | 摘要批量回写后详情立即生效 | PASS | updated 1 / skipped 1 | 57.2ms |
| M2-E01 | 内部快照接口校验令牌 | PASS | 401 unauthorized | 14.1ms |
| M2-E02 | 内部快照 upsert 幂等且可更新排名 | PASS | upsert 1 → 更新 rank=1 | 72.1ms |
| M2-E03 | 保留策略状态统计（总数 / 最早 / 最新） | PASS | total=13 · 2026-06-24 → 2026-10-22 | 23.5ms |
| M2-E04 | 保留清理 dryRun 只统计不删除 | PASS | 命中 2 · 未删除 | 44.0ms |
| M2-E05 | 保留清理实际删除过期快照 | PASS | 删除 2 · 剩余 11 | 49.5ms |
| M2-F01 | 无任何快照时回退 trending_repositories | PASS | 删除 11 条后回退 6 条 | 52.1ms |
| M2-P01 | 性能抽样 P95 < 300ms | PASS | P50 29.4ms / P95 38.3ms | 38.3ms |

## 性能抽样（预算 P95 < 300ms）

| 场景 | 样本数 | P50 | P95 | Max | 结果 |
| --- | --- | --- | --- | --- | --- |
| `/api/trending?limit=100` | 100 | 29.4ms | 38.3ms | 69.0ms | PASS |

## 汇总

- PASS：24
- GAP：0
- FAIL：0
- SKIP：0
- 结论：全部通过

