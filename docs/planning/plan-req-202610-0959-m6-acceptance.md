# 实施计划 · REQ-202610-0959 · M6 验收与回顾

> 文档编号：PL-REQ-0959 ｜ 维护人：fntp ｜ 创建日期：2026-10-22
>
> 关联需求：`docs/requirements/backlog.md` · M6-12（M6 · 检索与知识库深化）｜ 依赖：M6-01~11
>
> 验收口径：以平台已交付并合并的能力为准；未交付项单列缺口与再验收条件，不虚报通过。

## 1. 目标与范围

把 M6 已完成的检索与知识库能力整合到一条可交付验收分支，做一次跨分支端到端验收，
修复集成问题，并把验收矩阵、原始报告与复跑方式固化为文档。

范围：

- 验收对象：全文检索（M6-01）、相似推荐（M6-02）、重复检测（M6-03）、
  技术栈图谱（M6-04）、项目健康度（M6-05）、License 合规（M6-06）、
  依赖分析（M6-07）、知识库导出（M6-08）；
- 集成对象：0948、0949、0950、0951、0952、0953、0954、0955；
- 缺口登记：M6-09 多轮问答式检索（REQ-202610-0956）、M6-10 检索体验精修
  （REQ-202610-0957）、M6-11 主题聚类与自动标签（REQ-202610-0958）在验收时
  平台状态仍为 `pending`，不纳入本轮“已交付”结论，只做缺口检查与再验收条件说明；
- 不在本轮范围：真实 GitHub / Cloudflare / D1 线上流量验收、真实 LLM 多轮问答、
  生产规模性能压测；由本地替身、纯函数测试与 API 契约检查覆盖。

## 2. 实施步骤

1. 从 `origin/main`（`v1.0.0` / `53ab76f`）拉出 `feat/req-202610-0959-m6-acceptance` 工作树；
2. 按依赖顺序 `git merge --no-ff` 集成 0948~0955，解决 `config.py`、`schemas.py`、
   `models.py`、`tasks/jobs.py`、`edge/src/index.ts`、`edge/src/types.ts`、`docs/*`
   的交汇冲突，保留能力超集与 M5 已有行为；
3. 统一迁移编号：`0010_repo_health.sql` → `0014_repo_health.sql`、
   `0010_license_compliance.sql` → `0015_license_compliance.sql`；
   统一 `open-questions.md` 编号，避免与既有 Q14 / Q15 / Q24 冲突；
4. 新增 `vps/scripts/m6_acceptance.py`：启动真实 `uvicorn` + 临时 SQLite，
   校验 M6-01~08 的 API 契约与关键行为，并对 M6-09~11 输出缺口状态；
   支持 `--strict`、`--report-md`、`--report-json`、`--keep`；
5. 串行跑三端检查：vps pytest、edge typecheck / 测试、admin lint / build / test；
6. 生成 `acceptance-m6.md` 与 `acceptance-m6-report.md` / `.json`；
7. 更新 backlog / task-planning / roadmap / docs README / 各子项目 README；
8. 提交并推送需求分支，按平台要求回写执行存根与完成回调。

## 3. 验收矩阵

| 编号 | 验收点 | 覆盖方式 |
| --- | --- | --- |
| M6-01 | 全文检索 | 脚本 M6-A：`repo_readmes` + FTS5 虚表 / 触发器存在；全文检索、状态、重建接口契约；中文 / 英文命中与短词 LIKE 回退 |
| M6-02 | 相似推荐 | 脚本 M6-B：种子向量存在时 `/api/search/similar` 返回近邻与分数；种子缺失时 404 / 409 语义正确 |
| M6-03 | 重复检测 | 脚本 M6-C：名称 / 简介近似仓库形成簇，返回保留项、合并建议与阈值 |
| M6-04 | 技术栈图谱 | 静态检查 edge `GET /api/tech-stack` 路由与纯函数聚合、admin `/tech-stack` 页面与单测 |
| M6-05 | 项目健康度 | 脚本 M6-D：`/api/repos/health` 列表 / 单仓库 / 刷新入队契约；active / stale / archived 分档 |
| M6-06 | License 合规 | 脚本 M6-E：目录 / 汇总接口；SPDX → 分类 / 风险 / 义务派生；单仓库提示 |
| M6-07 | 依赖分析 | 脚本 M6-F：聚合接口返回 summary / techStack / ecosystems / dependencies；依赖入库与语言关联 |
| M6-08 | 知识库导出 | 静态检查 edge `/api/export/knowledge` 与 Markdown / JSON / Obsidian 纯函数、admin `/export` 页面与单测 |
| M6-09~11 | 未交付缺口 | 脚本 M6-G：检查对应路由 / 页面 / 分支不存在或未合并，输出 `gap` 状态，不计入通过率 |
| M6-12 | 验收与回顾 | 本计划 + `acceptance-m6.md` + 脚本报告 + 三端检查结果 |

## 4. 交付物

- `vps/scripts/m6_acceptance.py`（可重复执行，支持 `--strict`、`--report-md`、`--report-json`、`--keep`）；
- `docs/planning/acceptance-m6.md`（验收结论与矩阵）；
- `docs/planning/acceptance-m6-report.md` / `.json`（脚本生成的原始报告）；
- 文档同步：backlog / task-planning / roadmap / docs README / admin / edge / vps README。

## 5. 风险与处理

| 风险 | 处理 |
| --- | --- |
| 八个分支同时改 `config.py` / `schemas.py` / `models.py` / 文档 | 按依赖顺序合并，冲突处保留能力超集，逐次编译 / 跑测试 |
| 迁移编号 0010 / 0011 冲突 | 统一重排为 0014 / 0015，并同步所有文档引用 |
| M6-09~11 未交付导致验收范围争议 | 以平台状态为准，单列缺口与再验收条件，不虚报通过 |
| 相似 / 重复检测依赖向量与阈值 | 验收库显式灌入同模型 / 同维度向量，阈值用默认值，结果可重复 |
| 多任务共用机器 | 所有 pytest / build / test 走 `bacs-heavy`，串行执行，开跑前检查负载与内存 |
