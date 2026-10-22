# 任务计划 · REQ-202610-0902 标签体系 CRUD（重命名 / 合并 / 计数维护）

> 需求：REQ-202610-0902（backlog M1-10 / IT-0009）｜ 依赖：M1-02（`tags` / `repo_tags` 已建模）
> 分支：`feat/req-202610-0902-tags-crud` ｜ 基线：`feat/req-202610-0746-writeback`

## 1. 现状与缺口

- `edge/migrations/0001_init.sql` 已建 `tags(id, name UNIQUE, count)` 与 `repo_tags(repo_id, tag_id)`；
- 现有接口只有 `GET /api/categories` 顺带返回 `{name, count}`，没有标签的增删改查；
- `tags.count` 是冗余计数，目前没有任何写入路径维护，后续仓库打标 / 同步会产生漂移；
- admin「分类与标签」页仅把标签渲染成只读 Badge，没有管理入口。

## 2. 范围

### 2.1 edge API（新增 `edge/src/routes/tags.ts`）

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/tags` | GET | 列表，支持 `?q=`、`?sort=name\|count`、`?order=asc\|desc` |
| `/api/tags` | POST | 新建标签 `{ name }`，重名返回 409 `tag_name_exists` |
| `/api/tags/:id` | PATCH | 重命名 `{ name }`，重名返回 409 |
| `/api/tags/:id` | DELETE | 删除标签并解除仓库关联，返回解除数量 |
| `/api/tags/:id/merge` | POST | 合并到目标标签 `{ targetId }`，迁移关联后删除源标签 |
| `/api/tags/recount` | POST | 全量重算 `tags.count`，返回总数与修复数 |

- 所有端点要求登录会话（`c.get('user')`），未登录 401 `unauthorized`；
- 名称校验：去首尾空白、压缩连续空白、长度 1~50、禁止逗号（仓库列表用逗号拼接标签）与控制字符；
- 名称唯一性按大小写不敏感（`COLLATE NOCASE`）判断，避免 `React` / `react` 并存；
- 合并使用 D1 `batch` 原子执行：`INSERT OR IGNORE` 迁移关联 → 删除源关联 → 删除源标签 → 重算目标计数。

### 2.2 计数维护

- 新增迁移 `edge/migrations/0002_tag_count_triggers.sql`：在 `repo_tags` 的 INSERT / DELETE 后重算对应 `tags.count`，保证任何写入路径（含后续打标、同步、手工 SQL）都自动维护；
- 写接口在创建 / 合并 / 删除后重算相关标签计数；`POST /api/tags/recount` 作为存量修复入口；
- 列表查询以 `repo_tags` 实时计数为准，冗余列只作缓存，避免历史漂移影响展示。

### 2.3 admin（新增 `admin/src/features/tags/` + 路由 `/tags`）

- 标签列表：搜索、按名称 / 引用数排序、引用数展示；
- 新建 / 重命名对话框，重名给出可读提示；
- 合并对话框：选择目标标签，提示「源标签将被删除、关联仓库迁移到目标标签」；
- 删除确认：提示将解除多少仓库关联；
- 「重算计数」按钮，展示修复数量；
- 演示模式（无 `VITE_API_BASE_URL`）下使用本地状态模拟全部操作，保证页面可独立预览。

### 2.4 文档

- `docs/architecture/data-model.md`：补充 `tags.count` 维护机制与触发器；
- `docs/architecture/overview.md`：接口边界新增 `/api/tags` 系列；
- `docs/planning/task-planning.md`：IT-0009 状态更新；
- 本计划文档随分支提交。

## 3. 验证计划

| 检查 | 命令 | 通过条件 |
| --- | --- | --- |
| edge 类型 | `cd edge && npm run typecheck` | 0 error |
| edge 纯逻辑单测 | `cd edge && npm run test:scripts` | 全绿（名称归一 / 校验 / 合并计数） |
| admin lint | `cd admin && npm run lint` | 0 error |
| admin build | `cd admin && npm run build` | 成功（含 routeTree 重新生成） |
| admin 单测 | `cd admin && npm run test` | 全绿 |
| vps 回归 | `cd vps && .venv/bin/pytest -q` | 全绿（本次不改 vps，作回归） |

> 重活统一走 `bacs-heavy`，开跑前检查 `uptime` / `nproc` / `free -g`。

## 4. 风险与处理

1. **并行任务冲突**：`edge/src/index.ts`、`admin/src/components/layout/data/sidebar-data.ts`、`admin/src/lib/api.ts` 可能被同批任务同时修改；本分支保持最小改动，合并时按实际代码手工解冲突。
2. **admin 基线缺 `sidebar-data.ts`**：基线被 `.gitignore` 的 `**/data/` 误伤，本分支带入既有修复（补文件 + 例外规则），否则 admin 无法构建。
3. **D1 迁移未应用**：远程 D1 需在部署时执行 `npm run db:migrate:local` / 远程迁移；未应用时触发器不存在，但接口仍可用 `recount` 修复。
4. **标签为全局资源**：当前无多租户隔离，与既有 `tags` 表设计一致；后续如引入用户级标签需另立迁移。

## 5. 交付物

- edge：标签路由、纯逻辑模块、迁移、类型、单测；
- admin：标签管理页、API 客户端、路由、导航入口；
- docs：数据模型 / 接口边界 / 排期 / 本计划；
- 分支提交与推送（fork + PR，沿用本批既有方式）。
