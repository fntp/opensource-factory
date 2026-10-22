# 文档中心 · Docs

本目录是「开源项目工厂 / OpenFactory」的**唯一文档来源**：所有规范、规划、需求、架构与数据资产都存放在这里（需求 REQ-202610-0454 立项要求 #4）。

## 目录导航

| 目录 | 内容 | 入口 |
| --- | --- | --- |
| `standards/` | 规范落实：项目规范 / 代码约束 / 需求规范 / 编码规范 | [project-spec.md](./standards/project-spec.md) |
| `guides/` | Agent 维护、开发周期、部署基线 / 正式部署、本机一体化、备份恢复、热榜数据保留等运维手册 | [operations-runbook.md](./guides/operations-runbook.md) · [agent-maintenance.md](./guides/agent-maintenance.md) · [deployment-baseline.md](./guides/deployment-baseline.md) · [production-deployment.md](./guides/production-deployment.md) · [security-audit.md](./guides/security-audit.md) · [local-allinone-deployment.md](./guides/local-allinone-deployment.md) · [resource-budget-verification.md](./guides/resource-budget-verification.md) · [backup-restore.md](./guides/backup-restore.md) · [trending-retention.md](./guides/trending-retention.md) |
| `planning/` | 路线图、计划文档、资源规划、验收报告 | [roadmap.md](./planning/roadmap.md) · [task-planning.md](./planning/task-planning.md) · [resource-plan.md](./planning/resource-plan.md) · [REQ-0912 摘要质量计划](./planning/plan-req-202610-0912-summary-quality.md) · [REQ-0916 热榜保留计划](./planning/plan-req-202610-0916-trending-retention.md) · [REQ-0918 M2 验收计划](./planning/plan-req-202610-0918-m2-acceptance.md) · [M2 验收报告](./planning/acceptance-m2.md) · [REQ-202610-0920 向量化管线](./planning/plan-req-202610-0920-vector-pipeline.md) · [REQ-202610-0921 Vectorize 同步](./planning/plan-req-202610-0921-vectorize-sync.md) · [REQ-202610-0928 查询理解](./planning/plan-req-202610-0928-query-understanding.md) · [REQ-202610-0929 M3 验收计划](./planning/plan-req-202610-0929-m3-acceptance.md) · [M3 验收报告](./planning/acceptance-m3.md) · [REQ-202610-0937 推送记录与回执](./planning/plan-req-202610-0937-push-records.md) · [REQ-202610-0939 正式部署](./planning/plan-req-202610-0939-production-deploy.md) · [REQ-202610-0940 本机一体化](./planning/plan-req-202610-0940-local-allinone.md) · [REQ-202610-0941 监控与告警](./planning/plan-req-202610-0941-monitoring-alerting.md) · [REQ-202610-0942 备份恢复](./planning/plan-req-202610-0942-backup-restore.md) · [REQ-202610-0944 资源预算](./planning/plan-req-202610-0944-resource-budget.md) · [REQ-202610-0945 运维手册](./planning/plan-req-202610-0945-operations-runbook.md) · [REQ-202610-0946 安全审计](./planning/plan-req-202610-0946-security-audit.md) · [REQ-202610-0947 M5 验收计划](./planning/plan-req-202610-0947-m5-acceptance.md) · [M5 验收报告](./planning/acceptance-m5.md) · [v1.0.0 发布说明](./planning/release-v1.0.md) · [REQ-202610-0948 全文检索](./planning/plan-req-202610-0948-fulltext-search.md) · [REQ-202610-0949 相似推荐](./planning/plan-req-202610-0949-similar-recommendations.md) · [REQ-202610-0950 重复检测](./planning/plan-req-202610-0950-duplicate-detection.md) · [REQ-202610-0951 技术栈图谱](./planning/plan-req-202610-0951-tech-stack-graph.md) · [REQ-202610-0962 精选报告](./planning/plan-req-202610-0962-weekly-monthly-report.md) · [REQ-202610-0965 模型路由](./planning/plan-req-202610-0965-model-routing.md) |
| `requirements/` | 需求规格、功能梳理、需求池、待确认问题 | [spec.md](./requirements/spec.md) · [backlog.md](./requirements/backlog.md) |
| `architecture/` | 架构总览、数据模型 | [overview.md](./architecture/overview.md) |
| `integration/` | 参考项目集成说明 | [reference-projects.md](./integration/reference-projects.md) |
| `assets/` | 数据资产（D1 Schema 等） | [d1-schema.sql](./assets/d1-schema.sql) |

## 维护约定

1. **单一事实来源**：文档与代码不一致时，以实际代码与 `standards/` 规范为准，并尽快修正文档；
2. **同步义务**：行为 / 结构 / 接口 / 数据模型变更时，必须在同一提交内更新对应文档（对照表见 [AGENTS.md](../AGENTS.md) 第 5 节）；
3. **新增文档**：放入对应分类目录，并更新本索引；
4. **数据资产**：SQL、Schema、样例数据等放入 `assets/`，保持与 `edge/migrations/` 一致；
5. 文档语言统一使用中文（代码标识符保留英文）。
