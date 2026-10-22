# 实施计划 · REQ-202610-0894 D1 数据库创建与迁移应用

> 对应需求：REQ-202610-0894（backlog M1-02 / IT-0004）｜ 分支：`feat/req-202610-0894-d1-migration`｜ 日期：2026-10-22

## 1. 目标

把「创建 D1 数据库 → 替换 `database_id` → 应用迁移 → 校验 schema」做成一条可复现命令，并在无 Cloudflare 账号（Q3 未就绪）的前提下先用 `wrangler --local` 完成本地闭环验证。

## 2. 现状与约束

- `edge/wrangler.toml` 中 `database_id = "REPLACE_WITH_D1_DATABASE_ID"`，部署前必须替换；
- 迁移文件只有 `edge/migrations/0001_init.sql`，`docs/assets/d1-schema.sql` 为其同步副本；
- 依赖人工 Cloudflare 账号（账号 ID / API Token），本机当前无凭据，**不能伪造远程 id，也不能把真实 id 写进提交**；
- 约束：不强推、不删他人分支；token 不回显、不入库；本地验证使用 `.wrangler/`（已 gitignore）。

## 3. 方案

新增 `edge/scripts/d1-bootstrap.mjs`（Node 22，零第三方依赖），提供三个子命令：

| 命令 | 行为 |
| --- | --- |
| `local` | `wrangler d1 migrations apply opensource-factory --local` → 查询 `sqlite_master` 校验 8 张表与 8 个索引 → 二次执行验证幂等 |
| `remote` | 校验凭据 → `wrangler d1 list --json` 按名称查找数据库，不存在则 `d1 create` → 解析 `database_id` 并原子改写 `wrangler.toml` → `migrations apply --remote` → 远端校验表 / 索引 |
| `check` | 校验 `wrangler.toml` 绑定结构、`database_id` 格式（占位符仅告警）；比对迁移文件与 `docs/assets/d1-schema.sql` 归一化后一致；`--require-id` 时占位符直接失败（部署门禁） |

配套：

- `edge/package.json` 增加 `db:bootstrap:local` / `db:bootstrap:remote` / `db:check` / `db:check:remote` / `test:scripts`；
- `edge/scripts/d1-bootstrap.test.mjs` 覆盖 TOML 改写、id 校验、JSON 提取、SQL 归一化；
- 文档同步：`edge/README.md`、`AGENTS.md` §6、`docs/architecture/data-model.md`、`docs/requirements/open-questions.md`（Q3）、`docs/planning/task-planning.md`（IT-0004 状态）。

## 4. 验证

```bash
cd edge
bacs-heavy npm ci
npm run db:bootstrap:local   # 本地迁移 + 表/索引校验 + 幂等复跑
npm run test:scripts
npm run typecheck
```

远程步骤因缺 Cloudflare 账号无法执行，保留为人工事项：提供 `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` 后运行 `npm run db:bootstrap:remote`。

## 5. 文件清单

| 文件 | 说明 |
| --- | --- |
| `edge/scripts/d1-bootstrap.mjs` | 本地 / 远程创建与迁移引导脚本 |
| `edge/scripts/d1-bootstrap.test.mjs` | 脚本纯函数单测（node:test） |
| `edge/package.json` | 新增 npm scripts |
| `edge/README.md` | D1 创建 / 迁移 / 校验操作说明 |
| `AGENTS.md` / `docs/**` | 已知事项、Q3、迭代状态同步 |
