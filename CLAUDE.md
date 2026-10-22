# CLAUDE.md

本文件为 Claude Code 在此仓库工作时的快速指引。完整规则见 [AGENTS.md](./AGENTS.md) 与 [docs/](./docs/README.md)。

## 项目速览

开源项目工厂（OpenFactory）：个人开源资产管理与智能推荐系统。
Monorepo：`admin/`（React 前端）· `edge/`（Cloudflare Workers API）· `vps/`（Python 算力节点）· `docs/`（文档与数据资产）。

## 常用命令

```bash
# admin（前端）
cd admin
npm run dev          # 开发服务器
npm run lint         # ESLint
npm run build        # tsc -b && vite build（会重新生成 routeTree.gen.ts）
npm run test         # Vitest 浏览器模式（无头）
npm run format       # Prettier

# edge（边缘 API）
cd edge
npm run dev          # wrangler dev
npm run typecheck    # tsc --noEmit
npm run db:migrate:local

# vps（算力节点）
cd vps
.venv/bin/uvicorn app.main:app --reload
.venv/bin/pytest -q
```

## 硬性约束（务必遵守）

1. **不直接修改 `main` 分支**；在 `feat/req-*` 需求分支上工作。
2. **任何 token / 密钥不得回显到日志、不得写进提交**；不读取无关的密钥文件。
3. 完成前运行对应子项目的检查（lint / build / test / typecheck / pytest），全绿才算完成。
4. 行为变更同步更新 `docs/` 文档；不确定的问题记入 `docs/requirements/open-questions.md`。
5. 提交信息用 Conventional Commits + 中文描述，末尾附 `Co-Authored-By: Claude Code <noreply@anthropic.com>`。

## 目录内约定

- `admin/src/routes/**` 为 TanStack Router 文件式路由；新增页面需同时创建 `routes/` 文件与 `features/` 组件；`routeTree.gen.ts` 自动生成，勿手改。
- `admin/src/features/<feature>/` 内聚 api.ts（真实 API 调用 + 类型）+ 组件；统一使用 `apiFetch`，不使用演示数据兜底，页面需覆盖加载 / 空 / 错误三态。
- `edge/src/routes/*.ts` 按资源划分；SQL 一律通过 D1 绑定 `DB`，禁止在客户端暴露任何密钥。
- `vps/app/services/*` 单一职责；对外部依赖（LLM / 模型）必须有降级路径，测试不得依赖网络。
