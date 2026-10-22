# 代码约束规范 · Code Constraints

> 规范编号：STD-02 ｜ 适用范围：admin / edge / vps ｜ 维护人：fntp

## 1. 通用约束（所有子项目）

1. **类型安全**：TypeScript 严格模式（`strict: true`），禁止无理由的 `any`；Python 全量类型注解；
2. **禁止硬编码密钥**：任何 token / secret 不得出现在源码、注释、测试与提交中；一律走环境变量；
3. **测试不得依赖外网**：单元测试使用 fixture / mock；对外部服务的调用必须有降级路径；
4. **错误处理**：不允许空 catch；要么恢复、要么降级并记录（见各子项目细则）；
5. **格式化**：提交前必须通过子项目格式化 / Lint 检查。

## 2. admin（前端）

- 技术栈：React 19 + TypeScript + Vite + TanStack Router（文件式路由）+ TanStack Query + Tailwind 4 + shadcn/ui；
- 目录约定：
  - `src/routes/**`：仅做路由声明，组件从 `src/features/**` 引入；
  - `src/features/<feature>/`：内聚 `api.ts`（接口调用 + 类型定义）与页面组件；
  - `src/components/ui/**`：shadcn/ui 基础组件，**不直接改**（定制走业务组件或扩展）；
  - `src/lib/**`：与框架无关的工具；
- 数据获取：统一走 `@tanstack/react-query` + `src/lib/api.ts` 的 `apiFetch`（真实边缘 API，Cookie 会话，`credentials: 'include'`）；
- 不使用演示数据 / mock 兜底：接口失败时展示可读错误与重试入口，禁止静默回退到假数据；
- 页面必须区分并实现三种状态：加载中（`LoadingState`）、空数据（`EmptyState`，与「搜索无结果」分开）、请求失败（`ErrorState` + 重试）；
- 会话：登录态以 `GET /api/auth/me` 为准（httpOnly Cookie），401 跳转 `/sign-in`，网络 / 5xx 展示可重试错误态，不得误判为未登录；
- `src/routeTree.gen.ts` 自动生成，禁止手改；新增路由后运行 `npm run build` 或 `npx vite build` 重新生成。

## 3. edge（Cloudflare Workers）

- 技术栈：Hono + TypeScript + D1；禁止使用 Node.js 专有 API；
- 路由按资源拆分在 `src/routes/*.ts`，在 `src/index.ts` 统一挂载；
- 所有 SQL 通过 D1 绑定 `DB` 执行；迁移文件放 `migrations/`，命名 `NNNN_<描述>.sql`；
- 会话与 Cookie：会话 token 只存哈希；Cookie `httpOnly`；生产环境 `Secure`；
- 返回 JSON 统一形状：错误 `{ "error": "<code>" }`；列表直接返回数组或 `{ items, total }`；
- 任何密钥只从 `env` 读取，**不得写入 wrangler.toml 的明文 vars**（secrets 走 `wrangler secret put`）。

## 4. vps（Python 算力节点）

- 技术栈：Python 3.12 + FastAPI + SQLAlchemy 2.0 + Celery；风格遵循 PEP 8；
- 分层：`app/api/`（HTTP 层，只做参数校验与编排）→ `app/services/`（业务逻辑，单一职责）→ `app/tasks/`（Celery 任务，薄封装）；
- 外部依赖降级要求：
  - LLM（Ollama / DeepSeek）不可用 → 返回清洗后的截断文本并附说明；
  - 重型模型（torch / BGE-M3）未安装 → 使用确定性哈希向量兜底（保证测试可跑）；
  - 爬虫目标站不可用 → 返回空列表并记录日志，不抛未捕获异常；
- 内部接口鉴权：当设置 `INTERNAL_TOKEN` 时，`/api/tasks/*` 必须校验 `X-Internal-Token`；
- 测试：`pytest`，不访问网络；新增服务必须配套单测。

## 5. 提交前检查清单

```bash
# admin
cd admin && npm run lint && npm run build && npm run test

# edge
cd edge && npm run typecheck

# vps
cd vps && .venv/bin/pytest -q
```

全绿方可提交；任何一项红灯必须修复或降级并记录原因。
