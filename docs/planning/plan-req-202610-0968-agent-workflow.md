# 实施计划 · REQ-202610-0968 Agent 工作流（自动整理 / 草稿生成）

> 需求：REQ-202610-0968（backlog M7-09）｜ 分支：`feat/req-202610-0968-agent-workflow`
> 依赖：M7-01 自动打标建议（REQ-202610-0960）、M7-02 自动分类建议（REQ-202610-0961）、M7-03 每周 / 月度精选报告（REQ-202610-0962）
> 目标：把「逐条采纳建议、手动整理收藏、再手写总结」串成一条可回放、可预览、可人工确认的 Agent 工作流。

## 1. 现状与缺口

- M7-01 / M7-02 已能生成标签建议与分类建议，但用户需要逐条采纳，缺少「按阈值批量整理」；
- M7-03 已能生成周期报告，但报告是固定周期、固定结构，无法基于当前收藏即时生成一份可编辑的分享草稿；
- 三块能力彼此独立：没有统一的执行记录、步骤时间线、草稿状态与结果回放；
- 用户需要的是「一键整理 + 一份能带走的草稿」，并且所有自动动作都要可解释、可回滚、可人工确认。

## 2. 方案总览

```
admin /agent（Agent 工作流）
  → GET  /api/agent/templates            工作流模板与默认参数
  → POST /api/agent/runs                 创建并同步执行一次工作流
       ├─ 读取当前用户收藏快照（名称 / 简介 / 语言 / Star / 分类 / 标签 / 摘要）
       ├─ 读取 pending 的 tag_suggestions / category_suggestions
       ├─ 调 VPS POST /api/agent/draft（确定性规则，不依赖网络模型）
       │    ↳ 生成执行计划 + 整理建议 + Markdown 草稿；VPS 不可达时 edge 本地兜底
       ├─ mode=apply 时按阈值应用高置信标签 / 分类建议（写 tags / repo_tags / category_id）
       ├─ 写入 agent_runs（计划 / 结果 / 统计）
       └─ 写入 agent_drafts（草稿正文 / 状态 / 元数据）
  → GET  /api/agent/runs[/:id]           执行记录与步骤时间线
  → GET  /api/agent/drafts[/:id]         草稿列表与详情
  → POST /api/agent/drafts/:id/status    标记草稿已采用 / 已丢弃
```

设计原则：

1. **人工在环**：默认 `mode=preview` 只出计划与草稿；用户显式选择 `mode=apply` 才写标签 / 分类；
2. **确定性**：VPS 与 edge 都使用模板化规则生成计划与草稿，不调用 LLM，测试可稳定断言；
3. **账号隔离**：edge 所有 SQL 带 `user_id`，VPS 只接收当前用户快照，不接触用户身份；
4. **幂等与可回放**：每次执行落一条 `agent_runs`，结果 JSON 保存动作明细；草稿独立成表，可反复查看；
5. **优雅降级**：VPS 不可达时 edge 用本地规则生成同样的计划结构与 Markdown 草稿。

## 3. 工作流模板

| 模板 | key | 行为 |
| --- | --- | --- |
| 自动整理 | `organize` | 汇总待处理标签 / 分类建议，按阈值生成整理计划；`apply` 模式批量应用 |
| 收藏草稿 | `draft` | 基于当前收藏、分类、标签生成一份 Markdown 收藏精选草稿 |
| 整理 + 草稿 | `full` | 先整理，再把本次整理结果写进草稿的「本次变更」一节 |

参数：`repoIds?`（默认全部，最多 200）、`threshold`（0.5~1.0，默认 0.75）、`mode`（`preview` / `apply`）、`focus?`（草稿主题，可选）。

## 4. 数据模型

`agent_runs`（迁移 `0015_agent_workflows.sql`）：

| 字段 | 说明 |
| --- | --- |
| `id` | `run_<timestamp>_<hash>` |
| `user_id` | 用户 id |
| `template` | `organize` / `draft` / `full` |
| `mode` | `preview` / `apply` |
| `status` | `completed` / `failed` |
| `threshold` | 本次阈值 |
| `repo_count` | 参与仓库数 |
| `plan` | 计划步骤 JSON |
| `result` | 执行结果 JSON（动作 / 统计 / 草稿 id） |
| `draft_id` | 关联草稿 id（可空） |
| `error` | 失败原因（可空） |
| `created_at` / `finished_at` | 时间 |

`agent_drafts`：

| 字段 | 说明 |
| --- | --- |
| `id` | `draft_<timestamp>_<hash>` |
| `user_id` / `run_id` | 归属与来源执行 |
| `kind` | `collection_digest` |
| `title` / `content` | 标题与 Markdown 正文 |
| `status` | `draft` / `applied` / `discarded` |
| `metadata` | 统计 / 亮点 JSON |
| `created_at` / `updated_at` | 时间 |

## 5. 接口

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/agent/templates` | GET | 模板列表与默认参数 |
| `/api/agent/runs` | GET | 执行记录（`status` / `limit` / `offset`） |
| `/api/agent/runs` | POST | 创建并执行（`template` / `mode` / `threshold` / `repoIds` / `focus`） |
| `/api/agent/runs/:id` | GET | 执行详情（计划 / 结果 / 草稿） |
| `/api/agent/drafts` | GET | 草稿列表（`status`） |
| `/api/agent/drafts/:id` | GET | 草稿详情 |
| `/api/agent/drafts/:id/status` | POST | `applied` / `discarded` |
| VPS `/api/agent/draft` | POST | 内部接口：生成计划 + 草稿（`X-Internal-Token`） |

## 6. 交付物

| 位置 | 内容 |
| --- | --- |
| `vps/app/services/agent_workflow.py` | 计划构建、整理建议、Markdown 草稿生成 |
| `vps/app/api/agent.py` / `schemas.py` / `main.py` | `/api/agent/draft` 内部接口 |
| `vps/tests/test_agent_workflow.py` | 计划 / 草稿 / 阈值 / API 契约用例 |
| `edge/src/agent/workflow.ts` | 模板、参数归一化、本地计划 / 草稿、DTO 纯函数 |
| `edge/src/routes/agent.ts` | 模板 / 执行 / 记录 / 草稿路由与 D1 读写 |
| `edge/migrations/0015_agent_workflows.sql` | `agent_runs` / `agent_drafts` |
| `edge/scripts/agent-workflow.test.mjs` | 纯函数 + 路由契约用例 |
| `admin/src/features/agent/*` | API、工具函数、页面、演示数据、Vitest |
| `admin/src/routes/_authenticated/agent/index.tsx` | 文件式路由 |
| `admin/src/components/layout/data/sidebar-data.ts` | 「开源资产 → Agent 工作流」 |
| 文档 | 本计划、架构总览、数据模型、D1 schema、backlog、roadmap、task-planning、README |

## 7. 测试与验收

| 层 | 用例 |
| --- | --- |
| vps | 模板归一化、阈值夹取、计划步骤、草稿 Markdown 结构、空收藏、焦点主题、API 鉴权 / 契约 |
| edge 纯函数 | 模板 / 模式 / 阈值归一化、repoIds 清洗、本地计划、本地草稿、DTO |
| edge 路由 | 未登录 401、参数校验、preview 不写标签、apply 写标签 / 分类、草稿状态流转、执行记录 |
| admin | 模板文案、统计卡、步骤状态、草稿状态文案、演示数据筛选、API 请求体 |
| 回归 | vps pytest、edge typecheck / test、admin lint / build / test |

验收标准：

1. `/agent` 可选择三种模板并执行，执行后能看到步骤时间线与结果统计；
2. `preview` 模式不修改标签 / 分类，`apply` 模式只应用达到阈值的建议且结果可回放；
3. 草稿页能预览 Markdown、复制 / 下载、标记已采用或丢弃；
4. 未登录接口 401，所有数据按当前用户隔离；
5. VPS 不可达时仍能生成计划与草稿；
6. 三端检查全绿，文档同步更新。

## 8. 风险与后续

- **自动应用风险**：阈值默认 0.75 且需显式 `apply`，草稿保留动作明细便于复核；后续可加撤销；
- **草稿表达固定**：本期使用确定性模板，后续可接 M7-06 模型路由生成更自然的文案；
- **数据量**：单次最多 200 个仓库，Markdown 体积可控；更大规模可改为异步任务；
- **定时执行**：本期只做手动触发，后续可复用 Cron 与内部令牌接口做每日自动整理。
