# AGENTS.md · Agent 维护指南

本文件面向在此仓库中工作的 AI Agent（Claude Code 等）。人类贡献者请先读 [CONTRIBUTING.md](./CONTRIBUTING.md)。

## 0. 开工前必读（按顺序）

1. 本文件（AGENTS.md）；
2. [docs/guides/agent-maintenance.md](./docs/guides/agent-maintenance.md)（维护细节与验证命令）；
3. [docs/standards/](./docs/standards/project-spec.md)（四份规范：项目 / 代码约束 / 需求 / 编码）；
4. 任务相关的最新文档：`docs/requirements/` 与 `docs/planning/`。

> 文档与代码冲突时，以**实际代码与规范文件**为准，并在完成后修正文档。

## 1. 仓库结构

| 目录 | 职责 | 技术栈 |
| --- | --- | --- |
| `admin/` | 前端控制台 | React 19 + Vite + TanStack Router + shadcn/ui + Tailwind 4 |
| `edge/` | 边缘 API（Cloudflare Workers） | Hono + TypeScript + D1 |
| `vps/` | 本地算力节点 | Python 3.12 + FastAPI + Celery + Ollama/BGE-M3 |
| `docs/` | 全部项目文档与数据资产 | Markdown + SQL |
| `.github/` | CI | GitHub Actions |

## 2. 执行约束（硬性）

- 先读取目标仓库的规范文件（AGENTS.md / CLAUDE.md / README / CONTRIBUTING / docs）；
- 检查当前 Git 分支、工作目录与未提交修改；**保护已有本地修改，不直接修改 `main`**；
- 在需求分支上开发（`feat/req-<编号>-<简述>`），提交后推送；**不强推、不删除他人分支**；
- **任何 token / 密钥不得回显到日志、不得写进提交**；只使用 `.env` 或平台密钥托管；
- 完成前必须运行各子项目规定的检查（见下），全绿才算完成；
- 遇到不确定的点：在 `docs/requirements/open-questions.md` 记录待确认问题（含选项），而不是自行假设；
- 完成后向任务平台回报：修改摘要、测试结果、提交哈希、仍需人工处理的问题。

## 3. 验证命令（提交前必须全绿）

```bash
# admin
cd admin && npm run lint && npm run build && npm run test

# edge
cd edge && npm run typecheck

# vps
cd vps && .venv/bin/pytest -q
```

## 4. 提交规范

- Conventional Commits，scope 用 `admin` / `edge` / `vps` / `docs` / `repo`，描述用中文；
- 提交信息末尾附：`Co-Authored-By: Claude Code <noreply@anthropic.com>`；
- 一个需求分支内的提交保持原子性，不要混入无关改动。

## 5. 文档同步义务

改动以下内容时必须同步更新文档：

| 改动 | 需更新的文档 |
| --- | --- |
| 目录结构 / 技术栈 | `docs/architecture/overview.md`、本文件 |
| 数据库表 / 字段 | `docs/architecture/data-model.md`、`docs/assets/d1-schema.sql` |
| 接口契约 | `docs/architecture/overview.md`（接口边界一节） |
| 需求范围 | `docs/requirements/` |
| 计划 / 里程碑 | `docs/planning/` |

## 6. 已知注意事项

- `admin/src/routeTree.gen.ts` 为自动生成文件，**不要手改**；新增路由后运行 `npx vite build` 重新生成；
- admin 测试为浏览器模式（Vitest + Playwright），服务器环境已配置 `headless: true`；新环境需 `npx playwright install chromium`；
- `edge/wrangler.toml` 中的 `database_id` 为占位符：本地用 `npm run db:bootstrap:local` 验证；有 Cloudflare 账号后运行 `npm run db:bootstrap:remote` 自动创建数据库、替换 id 并应用迁移；
- 所有 `.env.example` 中的值均为占位符，真实值由维护者配置。
