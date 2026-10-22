# REQ-202610-0969 · M7 验收与回顾（M7-10）执行计划

> 需求：M7 验收与回顾（backlog M7-10）｜依赖：M7-01~09｜执行日期：2026-10-22
> 验收分支：`feat/req-202610-0969-m7-acceptance`（基于 M6 验收 tip `6d20e1a`）

## 1. 范围与判定口径

- 本轮集成平台已交付的 **M7-01~07**（REQ-202610-0960~0966），逐项做代码合并、契约检查与端到端走查；
- **M7-08（LoRA 微调评估，REQ-202610-0967）** 与 **M7-09（Agent 工作流，REQ-202610-0968）**
  平台状态仍为 pending，本轮不合并其分支，按 M6 验收惯例登记为 GAP，待平台交付后补充验收；
- 判定：PASS = 行为符合需求；FAIL = 行为错误；GAP = 未纳入本轮交付的缺口（不计入通过率）；
  `--strict` 下存在 GAP 或 FAIL 时退出码非零。

## 2. 集成顺序

| 顺序 | 需求 | 分支 | 合并要点 |
| --- | --- | --- | --- |
| 1 | M7-01 自动打标 | `feat/req-202610-0960-auto-tagging` | `edge/src/index.ts` 路由、`vps/app/schemas.py` TagSuggestion 系列、sidebar |
| 2 | M7-02 自动分类 | `feat/req-202610-0961-auto-classification` | 分类建议 schema / 路由 / sidebar，`main.py` 路由去重 |
| 3 | M7-03 精选报告 | `feat/req-202610-0962-weekly-monthly-report` | `/api/reports` 与内部生成路由、Cron、admin `/reports` |
| 4 | M7-04 更新提醒 | `feat/req-202610-0963-repo-update-reminders` | `my_repositories` Release 基线五列、`repo_updates`、admin `/updates` |
| 5 | M7-05 Star 趋势 | `feat/req-202610-0964-star-trend-insights` | sidebar 整文件重建、`edge/src/types.ts` License 字段 |
| 6 | M7-06 模型路由 | `feat/req-202610-0965-model-routing` | `models.py` / `schemas.py` 双方能力并集、sidebar `/model-routing` |
| 7 | M7-07 Rerank | `feat/req-202610-0966-rerank` | 推荐表精排列、`/api/rerank/*`、admin 精排工作台 |

冲突策略：代码保留能力超集；文档按语义合并（完成项勾选、状态行合并）；
`routeTree.gen.ts` 先取 ours，最终构建重新生成。

## 3. 跨分支一致性修复

1. **迁移编号统一**：M6 已占用 `0013_duplicate_dismissals` / `0014_repo_health` / `0015_license_compliance`，
   M7 五个迁移顺延为 `0016_tag_suggestions` / `0017_category_suggestions` / `0018_curated_reports` /
   `0019_repo_updates` / `0020_rerank`，同步 `docs/assets/d1-schema.sql`、`edge/README.md` 与计划文档引用；
2. **迭代编号统一**：M7-01~10 使用 `IT-0054~IT-0063`，消除与 M6 `IT-0044~0052` 的重号；
3. **文档章节编号**：`architecture/overview.md` M7 顺延为 3.29~3.33（备份 3.28 归位），
   `architecture/data-model.md` 全量重排 3.1~3.24 并将 M7 四张表集中到 3.21~3.24；
4. **open-questions 重排**：Q1~Q9 保持稳定，Q10~Q34 按需求编号重排，删除重复的知识库导出条目；
5. **README 清理**：`edge/README.md` 迁移清单按实际文件重写，`docs/README.md` 合并重复的 planning 行。

## 4. 验收矩阵

| 能力 | 验收方式 |
| --- | --- |
| M7-01 自动打标 | VPS `POST /api/tag-suggestions/generate`：语言 / 框架 / 业务域命中、分数阈值、排除已有标签 |
| M7-02 自动分类 | VPS `POST /api/category-suggestions/generate`：业务线命中、Top N、可解释字段 |
| M7-03 精选报告 | edge 纯函数 + 路由 + Cron + admin 页面静态检查；D1 迁移 `0018` 存在 |
| M7-04 更新提醒 | `parse_version` / `is_major_bump` / `classify_update` 单元断言 + 迁移 `0019` |
| M7-05 Star 趋势 | edge `/api/star-trends` 聚合纯函数 + admin 页面静态检查 |
| M7-06 模型路由 | VPS `/api/model-routes` 总览 / 健康 / 非法任务 404 / 非法模型 400 |
| M7-07 Rerank | VPS `/api/rerank/preview` 与 `/api/rerank/apply`：排序变化、MMR 多样性、明细字段 |
| M7-08 / M7-09 | 分支未合并 → GAP 登记 |

## 5. 检查与交付

- 三端检查（串行，重活走 `bacs-heavy`）：`vps` pytest、`edge` typecheck + test、`admin` lint + build + test；
- 产出：`vps/scripts/m7_acceptance.py`、`docs/planning/acceptance-m7.md`、`acceptance-m7-report.md/json`；
- 回写：执行存根（先）→ 完成回调；提交并推送需求分支，不直接改 `main`。

## 6. 风险与遗留

- M7-08/09 未纳入：若平台随后交付，需补做集成与验收；
- 迁移编号变更仅发生在未上线分支，D1 正式环境尚未应用，无需数据迁移；
- 历史 M4/M5/M6 迁移存在 `0002` / `0010` / `0011` 前缀重复（既有问题，不在本轮改动范围），
  已在 `edge/README.md` 如实列出，后续统一迁移时处理。
