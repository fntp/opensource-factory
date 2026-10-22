# 文档中心 · Docs

本目录是「开源项目工厂 / OpenFactory」的**唯一文档来源**：所有规范、规划、需求、架构与数据资产都存放在这里（需求 REQ-202610-0454 立项要求 #4）。

## 目录导航

| 目录 | 内容 | 入口 |
| --- | --- | --- |
| `standards/` | 规范落实：项目规范 / 代码约束 / 需求规范 / 编码规范 | [project-spec.md](./standards/project-spec.md) |
| `guides/` | Agent 维护、开发周期、部署基线 / 正式部署、本机一体化、备份恢复、热榜数据保留等运维手册 | [operations-runbook.md](./guides/operations-runbook.md) · [agent-maintenance.md](./guides/agent-maintenance.md) · [deployment-baseline.md](./guides/deployment-baseline.md) · [production-deployment.md](./guides/production-deployment.md) · [security-audit.md](./guides/security-audit.md) · [local-allinone-deployment.md](./guides/local-allinone-deployment.md) · [resource-budget-verification.md](./guides/resource-budget-verification.md) · [backup-restore.md](./guides/backup-restore.md) · [trending-retention.md](./guides/trending-retention.md) · [knowledge-export.md](./guides/knowledge-export.md) · [data-import.md](./guides/data-import.md) |
| `planning/` | 路线图、任务规划、资源规划、计划文档与验收报告（`plan-req-*.md` / `acceptance-*.md`） | [roadmap.md](./planning/roadmap.md) · [task-planning.md](./planning/task-planning.md) · [resource-plan.md](./planning/resource-plan.md) · [REQ-202610-0945 运维手册](./planning/plan-req-202610-0945-operations-runbook.md) · [M2 验收](./planning/acceptance-m2.md) · [M3 验收](./planning/acceptance-m3.md) · [M5 验收](./planning/acceptance-m5.md) · [M6 验收](./planning/acceptance-m6.md) · [M7 验收](./planning/acceptance-m7.md) · [REQ-202610-0973 快捷入口评估](./planning/plan-req-202610-0973-quick-entry-eval.md) |
| `requirements/` | 需求规格、功能梳理、需求池、待确认问题 | [spec.md](./requirements/spec.md) · [backlog.md](./requirements/backlog.md) |
| `architecture/` | 架构总览、数据模型、专项评估 | [overview.md](./architecture/overview.md) · [快捷入口评估](./architecture/quick-entry-evaluation.md) |
| `integration/` | 参考项目集成说明 | [reference-projects.md](./integration/reference-projects.md) |
| `assets/` | 数据资产（D1 Schema、API 契约等） | [d1-schema.sql](./assets/d1-schema.sql) · [快捷入口 API 契约](./assets/quick-entry-api-contract.json) |

## 维护约定

1. **单一事实来源**：文档与代码不一致时，以实际代码与 `standards/` 规范为准，并尽快修正文档；
2. **同步义务**：行为 / 结构 / 接口 / 数据模型变更时，必须在同一提交内更新对应文档（对照表见 [AGENTS.md](../AGENTS.md) 第 5 节）；
3. **新增文档**：放入对应分类目录，并更新本索引；
4. **数据资产**：SQL、Schema、样例数据等放入 `assets/`，保持与 `edge/migrations/` 一致；
5. 文档语言统一使用中文（代码标识符保留英文）。
