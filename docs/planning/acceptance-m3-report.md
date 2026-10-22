# M3 验收报告（自动生成）

- 生成时间：2026-10-22T08:21:27+0000
- 分支 / 提交：feat/req-202610-0929-m3-acceptance / 72c9840
- 运行环境：Linux-6.8.0-138-generic-x86_64-with-glibc2.39 · Python 3.12.3
- 数据规模：8 个收藏库 / 12 个热榜仓库 / 1 个测试用户 / mock edge（Vectorize + 推荐反馈）
- 判定口径：PASS 通过 · GAP 能力未集成（阻塞） · FAIL 行为错误 · SKIP 跳过

## 检查结果

| # | 检查 | 结果 | 说明 | 耗时 |
| --- | --- | --- | --- | --- |
| M3-01 | 模型选型满足 2G 预算（bge-m3 int8 + ≤2B LLM） | PASS | embedding=1100MB · llm=1300MB · peak=1300/2048MB | 386.8ms |
| M3-02 | 全量向量化 20 条并落库 | PASS | 20 条（my 8 / trending 12）· backend=hash | 320.1ms |
| M3-03 | 单条向量详情可读取（dim=256） | PASS | my/me/payment-gateway · dim=256 | 6.8ms |
| M3-04 | 增量同步 upsert 20 条并按批提交 | PASS | upserted=20 · batches=3 | 157.4ms |
| M3-05 | 重复增量同步跳过未变化向量 | PASS | upserted=0 / skipped=20（增量幂等） | 54.4ms |
| M3-06 | 索引对账全部命中（无缺失 / 过期） | PASS | checked=20 / missing=0 / stale=0 | 36.9ms |
| M3-07 | 语义搜索命中支付相关项目 | PASS | 命中 5 条 · top=me/payment-gateway | 15.4ms |
| M3-08 | 语义搜索结果水合完整（描述 / 理由 / 链接） | PASS | me/payment-gateway · score=0.398002 | 16.1ms |
| M3-09 | 搜索 scope / topK 过滤生效 | PASS | scope=my · topK=2 | 8.5ms |
| M3-10 | 搜索状态返回覆盖率与词表统计 | PASS | totalVectors=20 · vocabulary={'techEntries': 65, 'conceptEntries': 55, 'aliases': 328} | 9.0ms |
| M3-11 | 每日推荐任务生成结果并落库 | PASS | 10 条推荐 | 164.0ms |
| M3-12 | 推荐排除已收藏 / 已忽略项目 | PASS | 10 条 · 已排除 saved/dismissed | 11.5ms |
| M3-13 | 每条推荐含中文理由与依据字段 | PASS | reason=「与你的收藏方向较为接近（相似度约 52%）；技术栈都涉及 Python；今日热榜…」· based_on=['相似度 52%', '语言 Python', '技术栈 Python', '今日 +850 stars'] | 8.1ms |
| M3-14 | 即时语义推荐返回理由与依据 | PASS | 5 条 · 首条 payment-gateway | 15.2ms |
| M3-15 | 反馈拉取 → 排除 → 推荐回写闭环 | PASS | 反馈拉取 1 次 · 回写 10 条 | 0.1ms |
| M3-16 | 推荐质量评估返回指标 / 扫描 / 调参建议 | PASS | samples=3 · F1=0.1905 · 推荐 minScore=0.2 | 29.4ms |
| M3-17 | 降级状态接口 5 项自检全 PASS | PASS | 5 项全 PASS · expectedBackend=hash | 11.5ms |
| M3-18 | 降级自检 CLI 可独立执行 | PASS | python -m app.degradation check --json · exit 0 | 486.7ms |
| M3-19 | 查询理解识别技术栈与同义词 | PASS | rewritten=「react 前端 frontend ui」 | 5.6ms |
| M3-20 | 查询理解可关闭（expand=false） | PASS | expand=false · 保持原查询 | 4.3ms |
| M3-21 | 查询向量接口返回向量与理解结果 | PASS | dim=256 · understanding 已返回 | 6.4ms |
| M3-P01 | 语义搜索 P95 < 500ms | PASS | P50 9.3ms / P95 13.4ms | 13.4ms |
| M3-P02 | 推荐列表 P95 < 300ms | PASS | P50 8.0ms / P95 9.7ms | 9.7ms |

## 性能抽样

| 场景 | 样本数 | P50 | P95 | Max | 结果 |
| --- | --- | --- | --- | --- | --- |
| `/api/search/query` | 30 | 9.3ms | 13.4ms | 15.4ms | PASS |
| `/api/recommend/list?user_id=2001&limit=50` | 30 | 8.0ms | 9.7ms | 10.5ms | PASS |

## 汇总

- PASS：23
- GAP：0
- FAIL：0
- SKIP：0
- 结论：全部通过
