# 实施计划 · REQ-202610-0929 · M3 验收与回顾

> 文档编号：PL-REQ-0929 ｜ 维护人：fntp ｜ 创建日期：2026-10-22
>
> 关联需求：`docs/requirements/backlog.md` · M3-11（M3 · 推荐引擎）｜ 依赖：M3-01~09

## 1. 目标与范围

把 M3 已完成的 9 个能力（并叠加同期 M3-10 查询理解增强）整合到一条可交付验收分支，
用真实 HTTP + 本地临时数据库做跨分支端到端走查，修复集成问题，并把验收矩阵、
原始报告、回顾结论与复跑方式固化为文档。

范围：

- 验收对象：模型预算与降级、向量化管线、Vectorize 索引同步、语义搜索、每日推荐、
  推荐理由、反馈闭环、推荐质量评估、降级自检、查询理解；
- 集成对象：0919（M3-01）、0920（M3-02）、0921（M3-03）、0922（M3-04）、
  0923（M3-05）、0924（M3-06）、0925（M3-07）、0926（M3-08）、0927（M3-09）、
  0928（M3-10）；
- 不在本轮范围：真实 BGE-M3 / Ollama 模型下载、真实 Cloudflare Vectorize 账号联调、
  真实 edge 生产环境；这些依赖由 mock edge + hash 兜底向量替代，接口契约保持一致。

## 2. 实施步骤

1. 从 `origin/main` 拉出 `feat/req-202610-0929-m3-acceptance` 工作树；
2. 按依赖顺序 `git merge --no-ff` 集成 0919~0928，解决 `config.py`、`schemas.py`、
   `runtime.py`、`docs/*`、`admin/*`、`edge/*` 的交汇冲突，保留能力超集；
3. 修复集成暴露的问题：重复 `VectorSyncRequest`、`REQUIRED_ENV_KEYS` 漂移、
   重复配置块、文档代码围栏错位等；
4. 新增 `vps/scripts/m3_acceptance.py`：自动建临时 SQLite、种入收藏库 / 热榜 /
   反馈数据集、启动 mock edge（Vectorize + 推荐反馈契约）与 `uvicorn`，按
   M3-A/B/C/D/E/F/G/H/P 分组执行断言；
5. 串行跑三端检查：vps pytest、edge typecheck / 测试、admin lint / build / test；
6. 生成验收报告，更新任务计划、需求池、路线图与文档索引。

## 3. 验收矩阵

| 编号 | 验收点 | 覆盖方式 |
| --- | --- | --- |
| M3-01 | 模型选型与 2G 预算 | CLI `python -m app.model_budget check --json`：bge-m3 int8 1100MB、LLM 1300MB，峰值 ≤ 2048MB |
| M3-02 | 向量化管线 | 脚本 M3-A01~A04：入队全量向量化 → 覆盖率 / 模型分布 / 单条向量 / 增量跳过 |
| M3-03 | Vectorize 索引同步 | 脚本 M3-B01~B04：mock edge upsert → 状态 synced / 增量跳过 / 对账 missing=0 |
| M3-04 | 语义搜索 | 脚本 M3-C01~C05：`/api/search/query`、`/semantic`、`/status`、topK / minScore |
| M3-05 | 每日推荐 | 脚本 M3-D01~D03：入队生成 → `/api/recommend/list` 有结果、已收藏被排除 |
| M3-06 | 推荐理由 | 脚本 M3-D04：每条推荐 `reason` 非空、`basedOn` 非空 |
| M3-07 | 反馈闭环 | 脚本 M3-E01~E03：mock 反馈排除 saved/dismissed、生成后回写 upsert 条数一致 |
| M3-08 | 质量评估 | 脚本 M3-F01~F02：`/api/recommend/eval` status=ok、指标 / 阈值 / 权重齐全 |
| M3-09 | 降级路径 | CLI `python -m app.degradation check --json` + `GET /api/degradation/status` 5 项全 PASS |
| M3-10 | 查询理解 | 脚本 M3-G01~G03：`/api/search/understand` 技术栈 / 同义词、`expand=false` 关闭扩展 |
| M3-11 | M3 验收与回顾 | 本计划 + `acceptance-m3.md` + 脚本报告 |

## 4. 交付物

- `vps/scripts/m3_acceptance.py`（可重复执行，支持 `--strict`、`--report-md`、`--report-json`、`--keep`）；
- `docs/planning/acceptance-m3.md`（验收结论与矩阵）；
- `docs/planning/acceptance-m3-report.md` / `.json`（脚本生成的原始报告）；
- M3 十个分支的集成代码与集成修复；
- 文档同步：backlog / task-planning / roadmap / docs README。

## 5. 风险与处理

| 风险 | 处理 |
| --- | --- |
| 十个分支同时改 `config.py` / `schemas.py` / 文档 | 按依赖顺序合并，冲突处保留能力超集，逐次编译 / 跑测试 |
| 本机无 BGE-M3 / Ollama | 验收统一 `EMBEDDING_FORCE_FALLBACK=1`（hash 256 维），Vectorize mock 索引维度同步为 256 |
| 无真实 Cloudflare Vectorize | 用本地 mock edge 实现 upsert / check / stats / delete 契约，验证 VPS 侧同步与对账逻辑 |
| 无真实 edge 推荐接口 | mock `/api/internal/recommendations/feedback` 与 `/upsert`，验证反馈排除与回写 |
| Celery 依赖 Redis | 验收进程设置 `CELERY_TASK_ALWAYS_EAGER=1`，任务在 API 进程内同步执行 |
| 多任务共用机器 | 所有 pytest / build / test 走 `bacs-heavy`，串行执行，开跑前检查负载与内存 |
