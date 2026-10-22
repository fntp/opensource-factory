# 实施计划 · REQ-202610-0903 仓库列表组合筛选与排序

> 需求：REQ-202610-0903（backlog M1-11）｜ 分支：`feat/req-202610-0903-repo-filter-sort`｜ 基线：`feat/req-202610-0746-writeback`（9e6c105）

## 1. 目标与范围

在「我的仓库」列表上提供**服务端组合筛选 + 排序**，避免前端全量拉取后内存过滤：

- 筛选维度：关键词、分类（含子分类）、标签（多选，AND）、语言（多选）、Star 区间、最近更新时间区间；
- 排序维度：Star、最近更新、收录时间、名称；支持升 / 降序；
- 筛选条件可组合，提供已选条件回显、单项移除与一键清空；
- 无后端时（`VITE_DEMO_MODE`）使用演示数据在本地执行同一套筛选 / 排序逻辑，保证页面可用。

不在本次范围：分页、全文 FTS、查询计划专项优化（M1-12）、分类 / 标签 CRUD（M1-09/10）。

## 2. API 设计（edge）

`GET /api/repos` 保持返回 `RepoItem[]`，新增查询参数：

| 参数 | 说明 |
| --- | --- |
| `q` | 关键词，匹配仓库名 / 全名 / owner / 描述 / 摘要 / 语言 / 分类名 / 标签名 |
| `categoryId` | 分类 id；默认包含其全部子孙分类（分类树无限级） |
| `tags` | 标签名，逗号分隔；多个标签为 **AND**（同时命中） |
| `tagIds` | 标签 id，逗号分隔；与 `tags` 等价，供标签管理页复用 |
| `languages` | 语言，逗号分隔；多个语言为 OR |
| `starsMin` / `starsMax` | Star 区间（非负整数，含边界） |
| `updatedAfter` / `updatedBefore` | 最近更新时间区间，`YYYY-MM-DD`（UTC，含边界） |
| `sort` | `stars`（默认）/ `updated` / `created` / `name` / `forks` |
| `order` | `desc`（默认）/ `asc` |

实现要点：

- 排序字段与方向使用白名单映射到 SQL，禁止拼接用户输入；
- 标签筛选使用 `EXISTS` 子查询，避免多标签 JOIN 产生重复行；
- 关键词 `LIKE` 对 `%` / `_` / `\` 转义；
- 分类过滤先读取分类表并在应用层展开子孙 id，再走 `IN (...)`；
- 非法数字 / 日期 / 排序值返回 `400 { error: "invalid_query", field }`；
- 新增迁移 `0003_repo_filter_indexes.sql`：`(user_id, stars DESC)`、`(user_id, updated_at DESC)`、`(user_id, language)`、`(user_id, category_id)`。

`GET /api/categories` 的 `tags` 增加 `id` 字段（标签筛选使用稳定 id 时需要），为向后兼容的追加字段。

## 3. admin 交互设计

- 顶部筛选栏：关键词输入（300ms 防抖）、分类下拉、标签多选、语言多选、Star 区间、更新时间区间、排序字段 + 升降序；
- 已选条件以 Badge 回显，支持单项移除与「清除全部」；
- 表格增加「语言」列；筛选栏展示当前排序字段与升 / 降序状态；
- 加载中、空结果、演示模式均有明确提示；
- 筛选 / 排序状态由 `features/repos/filters.ts` 的纯函数生成查询串，便于单测。

## 4. 验证计划

- `cd edge && npm run typecheck`；
- `cd edge && npm run test:repos`（node:test，覆盖参数解析、SQL 片段、排序白名单、日期边界）；
- `cd admin && npm run lint && npm run build && npm run test`（新增 filters 单测）；
- `cd vps && .venv/bin/pytest -q`（回归，确认无影响）；
- `git diff --check`；无密钥入库。

## 5. 风险与决策

| 风险 / 决策 | 处理 |
| --- | --- |
| 分类树过滤是否含子分类 | 默认包含；分类树语义下父分类应覆盖子分类资产 |
| 多标签语义 | AND（同时具备），更符合「组合筛选」的精确收窄预期 |
| 时间筛选基准 | 使用 `updated_at`（最近更新）；排序另提供 `created`（收录时间） |
| 演示模式 | 本地纯函数筛选，保证无后端时仍可演示全部交互 |
| 与 M1-09/10 分支并行 | 只依赖既有 categories / tags / repo_tags 表，不修改其 CRUD 代码；标签 id 为追加字段 |

## 6. 验证结果（2026-10-22）

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| edge 类型检查 | `cd edge && npm run typecheck` | 通过 |
| edge 查询单测 | `cd edge && npm run test:repos` | 7/7 通过 |
| admin Lint | `cd admin && npm run lint` | 通过 |
| admin 构建 | `cd admin && bacs-heavy npm run build` | 通过（exit 0） |
| admin 单测 | `cd admin && bacs-heavy npm run test` | 11 个文件 / 82 条通过 |
| vps 回归 | `cd vps && bacs-heavy .venv/bin/pytest -q` | 20 条通过 |
| 空白检查 | `git diff --check` | 通过 |
