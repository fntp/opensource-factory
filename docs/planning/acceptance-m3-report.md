# M3 验收报告（自动生成）

- 生成时间：2026-10-22T08:25:17+0000
- 分支 / 提交：feat/req-202610-0929-m3-acceptance / 22da214
- 运行环境：Linux-6.8.0-138-generic-x86_64-with-glibc2.39 · Python 3.12.3
- 数据规模：8 个收藏库 / 12 个热榜仓库 / 1 个测试用户 / mock edge（Vectorize + 推荐反馈）
- 判定口径：PASS 通过 · GAP 能力未集成（阻塞） · FAIL 行为错误 · SKIP 跳过

## 检查结果

| # | 检查 | 结果 | 说明 | 耗时 |
| --- | --- | --- | --- | --- |
| M3-01 | 模型选型满足 2G 预算（bge-m3 int8 + ≤2B LLM） | PASS | embedding=1100MB · llm=1300MB · peak=1300/2048MB | 340.2ms |
| M3-02 | 全量向量化 20 条并落库 | PASS | 20 条（my 8 / trending 12）· backend=hash | 274.9ms |
| M3-03 | 单条向量详情可读取（dim=256） | PASS | my/me/payment-gateway · dim=256 | 9.1ms |
| M3-04 | 增量同步 upsert 20 条并按批提交 | PASS | upserted=20 · batches=3 | 125.6ms |
| M3-05 | 重复增量同步跳过未变化向量 | PASS | upserted=0 / skipped=20（增量幂等） | 45.0ms |
| M3-06 | 索引对账全部命中（无缺失 / 过期） | PASS | checked=20 / missing=0 / stale=0 | 33.8ms |
| M3-07 | 语义搜索命中支付相关项目 | PASS | 命中 5 条 · top=me/payment-gateway | 13.1ms |
| M3-08 | 语义搜索结果水合完整（描述 / 理由 / 链接） | PASS | me/payment-gateway · score=0.398002 | 11.3ms |
| M3-09 | 搜索 scope / topK 过滤生效 | PASS | scope=my · topK=2 | 11.2ms |
| M3-10 | 搜索状态返回覆盖率与词表统计 | PASS | totalVectors=20 · vocabulary={'techEntries': 65, 'conceptEntries': 55, 'aliases': 328} | 7.0ms |
| M3-11 | 每日推荐任务生成结果并落库 | PASS | 10 条推荐 | 144.9ms |
| M3-12 | 推荐排除已收藏 / 已忽略项目 | PASS | 10 条 · 已排除 saved/dismissed | 6.9ms |
| M3-13 | 每条推荐含中文理由与依据字段 | PASS | reason=「与你的收藏方向较为接近（相似度约 52%）；技术栈都涉及 Python；今日热榜…」· based_on=['相似度 52%', '语言 Python', '技术栈 Python', '今日 +850 stars'] | 4.8ms |
| M3-14 | 即时语义推荐返回理由与依据 | PASS | 5 条 · 首条 payment-gateway | 15.7ms |
| M3-15 | 反馈拉取 → 排除 → 推荐回写闭环 | PASS | 反馈拉取 1 次 · 回写 10 条 | 0.0ms |
| M3-16 | 推荐质量评估返回指标 / 扫描 / 调参建议 | PASS | samples=3 · F1=0.1905 · 推荐 minScore=0.2 | 34.3ms |
| M3-17 | 降级状态接口 5 项自检全 PASS | PASS | 5 项全 PASS · expectedBackend=hash | 10.2ms |
| M3-18 | 降级自检 CLI 可独立执行 | PASS | python -m app.degradation check --json · exit 0 | 449.3ms |
| M3-19 | 查询理解识别技术栈与同义词 | PASS | rewritten=「react 前端 frontend ui」 | 4.8ms |
| M3-20 | 查询理解可关闭（expand=false） | PASS | expand=false · 保持原查询 | 3.9ms |
| M3-21 | 查询向量接口返回向量与理解结果 | PASS | dim=256 · understanding 已返回 | 6.7ms |
| M3-P01 | 语义搜索 P95 < 500ms | PASS | P50 8.5ms / P95 14.1ms | 14.1ms |
| M3-P02 | 推荐列表 P95 < 300ms | PASS | P50 4.8ms / P95 6.1ms | 6.1ms |

## 性能抽样

| 场景 | 样本数 | P50 | P95 | Max | 结果 |
| --- | --- | --- | --- | --- | --- |
| `/api/search/query` | 30 | 8.5ms | 14.1ms | 14.7ms | PASS |
| `/api/recommend/list?user_id=2001&limit=50` | 30 | 4.8ms | 6.1ms | 6.3ms | PASS |

## 汇总

- PASS：23
- GAP：0
- FAIL：0
- SKIP：0
- 结论：全部通过
