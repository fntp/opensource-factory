# 实施计划 · REQ-202610-0918 · M2 验收与回顾

> 文档编号：PL-REQ-0918 ｜ 维护人：fntp ｜ 创建日期：2026-10-22
>
> 关联需求：`docs/requirements/backlog.md` · M2-10（M2 · 热榜与摘要）｜ 依赖：M2-01~08

## 1. 目标与范围

把 M2 已完成的 8 个能力整合到一条可重复执行的验收分支，用真实 HTTP 请求完成热榜对外链路走查，抽样核对列表性能，并把结果、差距、回顾结论与复跑方式固化为文档。

范围：

- 验收对象：edge 热榜 API（按日快照、日期 / 语言筛选、趋势标注、详情摘要回退、一键收藏、摘要回写、快照 upsert、保留清理）；
- 集成对象：M2 并行需求分支 0909（每日抓取）、0910（容错告警）、0911（README 清洗）、0912（摘要质量）、0913（按日快照）、0914（热榜页）、0915（详情收藏）、0916（数据保留）；
- VPS 侧能力（抓取、解析、摘要、归档）由 `vps/pytest` 全量用例覆盖，验收报告引用其结果；
- 不在本轮范围：M2-09 Gitee 抓取（Q2 已确认本期不接入）、真实 GitHub / Cloudflare 生产凭据联调。

## 2. 实施步骤

1. 从 `origin/feat/req-202610-0746-writeback`（`9e6c105`）拉出 `feat/req-202610-0918-m2-acceptance` 工作树；
2. 按依赖顺序 `git merge --no-ff` 集成 0909~0916 分支，解决 `trending.py`、`schemas.py`、`jobs.py`、`types.ts`、`docs/*` 的交汇冲突，保留各分支能力超集；
3. 修复集成暴露的问题：`0008_trending_detail.sql` 与 `0007_trending_summary.sql` 重复添加 `readme_summary` 列；
4. 新增 `edge/scripts/m2-acceptance.mjs`：自动应用本地 D1 迁移、种入 6 个热榜仓库 / 13 条快照固定数据集、启动 `wrangler dev`，按 M2-A/B/C/D/E/F/P 分组执行断言；
5. 跑三端检查：edge typecheck / 脚本测试 / M2 验收，vps pytest，admin lint / build / test；
6. 生成验收报告，更新任务计划、需求池、路线图、数据模型与文档索引。

## 3. 验收矩阵

| 编号 | 验收点 | 覆盖方式 |
| --- | --- | --- |
| M2-01 | GitHub Trending 每日定时抓取 | VPS pytest：`test_trending_job` / `test_trending_pages`；脚本验证快照落 D1 契约 |
| M2-02 | 抓取容错与页面结构告警 | VPS pytest：`test_crawl_guard` / 告警 API；脚本不覆盖 VPS 本地告警表 |
| M2-03 | README 清洗与技术栈提取 | VPS pytest：`test_readme`；脚本校验 `tech_stack` 透出 |
| M2-04 | 中文摘要批量生成与质量抽检 | 脚本 M2-D01/D02（内部回写 + 详情生效）；VPS `test_summary_pipeline` |
| M2-05 | 按日快照与趋势字段 | 脚本 M2-A01/A04/B01/B03/E02 |
| M2-06 | 热榜页日期 / 语言筛选与趋势标注 | 脚本 M2-A02/A03/A05/A06/B02 |
| M2-07 | 热榜详情与一键收藏 | 脚本 M2-C01~C06 |
| M2-08 | 数据保留 / 归档 / 清理 | 脚本 M2-E03~E05；VPS `test_trending_retention` |
| M2-10 | M2 验收与回顾 | 本计划 + 验收报告 + 文档同步 |

## 4. 交付物

- `edge/scripts/m2-acceptance.mjs`（可重复执行，支持 `--strict`、`--report-md`、`--report-json`、`--keep`）；
- `docs/planning/acceptance-m2.md`（验收结论与矩阵）；
- `docs/planning/acceptance-m2-report.md` / `.json`（脚本生成的原始报告）；
- M2 八个分支的集成代码与迁移修复；
- 文档同步：backlog / task-planning / roadmap / data-model / docs README。

## 5. 风险与处理

| 风险 | 处理 |
| --- | --- |
| 八个分支同时改 `trending.py` / `types.ts` / 文档 | 按依赖顺序合并，冲突处保留能力超集，逐次跑 pytest / typecheck |
| 迁移重复加列（0007 / 0008） | 移除 0008 的重复 `ALTER TABLE`，仅保留索引 |
| VPS 抓取依赖外网 | 验收脚本只测 D1 契约；VPS 单测全部使用本地 fixture，不依赖网络 |
| 真实凭据缺失 | 本地 D1 + 种子数据覆盖；真实 GitHub / Cloudflare 联调列入遗留 |
