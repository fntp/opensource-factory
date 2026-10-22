# 实施计划 · REQ-202610-0980 数据导入（外部收藏迁移）

> 需求：REQ-202610-0980（backlog M9-03）｜ 分支：`feat/req-202610-0980-data-import`
> 依赖：M1-05 Starred 全量同步（已落地，`my_repositories` 与仓库元数据契约稳定）
> 目标：把浏览器书签、其他收藏工具与 OpenFactory 自身导出文件中的仓库，安全、可预览、可重复地迁移进当前用户的收藏库。

## 1. 现状与约束

- 收藏库 `my_repositories` 以 `owner/repo` 为**全局主键**，同一实例内不同用户不能重复收藏同一仓库；
  导入必须显式识别「已被其他用户收藏」的冲突条目并跳过，不能静默覆盖；
- M6-08 已定义 `openfactory.knowledge.v1` 导出格式（JSON），M9-04 会以它为归档基线；
  导入必须能原样吃回该格式，形成「导出 → 导入」闭环；
- 浏览器（Chrome / Edge / Firefox / Safari）普遍支持 Netscape Bookmark HTML 导出，
  这是「外部收藏」最现实的来源；CSV 用于表格工具与手工整理；
- 导入是一次性批量写操作，必须在写库前给出**预览**（新增 / 更新 / 冲突 / 无效），
  避免用户把几千条错误数据直接灌进收藏库；
- 解析全部在 edge Worker 内完成，不依赖 VPS / 网络；不采集、不上传任何第三方凭据。

## 2. 方案总览

```
admin /import
  → 选择文件（.json / .csv / .html）或粘贴文本
  → POST /api/import/preview  { content, format, useFolders }
     → parseImportContent：格式识别 → 解析 → 归一 → 文件内去重 → 与 D1 对比
     → 返回统计 + 前 50 条样例 + 问题清单（不写库）
  → POST /api/import/execute  { content, format, useFolders, createCategories }
     → 重新解析（不信任客户端归一结果）→ 逐条 upsert → 建分类 / 标签
     → 写 import_runs 历史 → 返回导入结果
  → GET /api/import/history?limit=10 最近导入记录
```

设计原则：

1. **先预览、后写入**：预览与执行共用同一套纯函数解析器，统计口径一致；
2. **幂等**：同一文件重复导入只会更新已有收藏，不产生重复仓库；文件内按 `owner/repo` 去重合并；
3. **用户隔离**：所有查询 / 写入都带当前会话用户；他人已收藏的仓库计为冲突并跳过；
4. **纯函数解析**：JSON / CSV / HTML 解析与 URL 归一全部在 `edge/src/import/parse.ts`，node:test 直接覆盖；
5. **可追溯**：每次执行写一条 `import_runs`，记录来源格式与各项计数，admin 展示最近记录。

## 3. 支持的格式

| 格式 | 识别方式 | 说明 |
| --- | --- | --- |
| JSON | 首个非空字符为 `{` / `[` | `openfactory.knowledge.v1`（读取 `repositories`）、`{ items: [...] }` 或对象数组；字段兼容 camelCase / snake_case |
| CSV | 非 JSON / HTML 且含分隔行 | 首行为表头，支持逗号 / 制表符 / 分号；引号、转义引号与字段内换行 |
| HTML | 含 `<a ... href=` 或 Netscape `<!DOCTYPE NETSCAPE-Bookmark-file-1>` | 浏览器书签导出；可选把书签文件夹映射为分类 |

字段别名（JSON / CSV 通用）：

| 目标 | 别名 |
| --- | --- |
| 仓库全名 | `fullName` / `full_name` / `repo` / `repository` / `id`（`owner` + `name` 亦可） |
| 链接 | `url` / `htmlUrl` / `html_url` / `link` |
| 描述 | `description` / `desc` |
| 摘要 | `summary` / `readmeSummary` / `readme_summary` |
| 语言 | `language` |
| Star / Fork | `stars` / `stargazers_count`、`forks` / `forks_count` |
| 分类 | `category` / `categoryName` / `category_name` |
| 标签 | `tags`（数组或逗号分隔字符串） |
| 平台 | `platform`（`github` / `gitee`，缺省按链接推断） |

## 4. 归一与校验规则

- 仅接受 GitHub / Gitee 仓库链接：`https://github.com/{owner}/{repo}`、`https://gitee.com/{owner}/{repo}`；
  子路径（`/tree/...`、`/issues`）截断为仓库根；`/topics/...`、`/trending` 等保留路径判为无效；
- 仓库名允许字母、数字、`_`、`.`、`-`，长度 1–100；链接协议仅 http / https；
- 文本压缩换行：描述 ≤ 500 字、摘要 ≤ 4000 字、分类 ≤ 100 字、单个标签 ≤ 50 字、每仓库最多 20 个标签；
- Star / Fork 取非负整数，上限 10,000,000；
- 单次内容 ≤ 2 MB、有效条目 ≤ 2000 条，超出部分截断并计入问题清单；
- 文件内按 `owner/repo` 大小写不敏感去重；重复条目合并标签、取非空字段与较大 Star；
- 与 D1 对比：无记录 = `new`；本人已有 = `update`；他人已有 = `conflict`（跳过并提示）。

## 5. 数据模型

`import_runs`（D1 迁移 `0022_data_import.sql`）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | TEXT PK | `imp_<timestamp>_<random>` |
| `user_id` | TEXT | 用户 id |
| `source_format` | TEXT | `json` / `csv` / `html` |
| `status` | TEXT | `completed`（预留 `failed`） |
| `total` / `imported` / `updated` / `skipped` / `conflicts` / `invalid` | INTEGER | 各项计数 |
| `categories_created` / `tags_created` | INTEGER | 本次新建的分类 / 标签数 |
| `created_at` | DATETIME | 执行时间 |

索引：`(user_id, created_at DESC)`。

## 6. 接口

| 端点 | 方法 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| `/api/import/preview` | POST | 登录态 | 解析并返回统计 / 样例 / 问题，不写库 |
| `/api/import/execute` | POST | 登录态 | 执行导入并写历史，返回计数 |
| `/api/import/history` | GET | 登录态 | 最近导入记录（默认 10，最多 50） |

错误码：`unauthorized` 401、`invalid_json` 400、`invalid_body` 400、`content_required` 400、
`content_too_large` 413、`unsupported_format` 400。

## 7. 文件清单

- 新增 `edge/src/import/parse.ts`（格式识别 / 三种解析器 / URL 归一 / 去重 / 计划）
- 新增 `edge/src/routes/import.ts`（预览 / 执行 / 历史）
- 新增 `edge/migrations/0022_data_import.sql`
- 修改 `edge/src/index.ts`（挂载 `/api/import`）、`edge/src/types.ts`（`ImportRunRow`）
- 新增 `edge/scripts/import-helpers.test.mjs`、`edge/scripts/import-route.test.mjs`
- 新增 `admin/src/features/import/{types,api,utils,index,import.test}.ts(x)`
- 新增 `admin/src/routes/_authenticated/import/index.tsx`；修改侧边栏与 `admin/README.md`
- 文档：本计划、`docs/guides/data-import.md`、架构总览、数据模型、D1 Schema、
  backlog、roadmap、task-planning、open-questions、`docs/README.md`、`edge/README.md`

## 8. 验证计划

```bash
cd edge && npm run typecheck && npm test
cd admin && npm run lint && npm run build && npm run test
cd vps && .venv/bin/pytest -q
git diff --check
```

验收标准：

1. JSON（`openfactory.knowledge.v1`）、CSV、浏览器书签 HTML 均可解析并给出正确统计；
2. 预览不写库；执行后收藏、分类、标签正确落库，重复执行不产生重复数据；
3. 他人已收藏仓库计为冲突并跳过，不影响其余条目；
4. 未登录 401，非法内容 400，超限 413，问题条目有明确原因；
5. admin 页面支持选文件 / 粘贴、格式切换、文件夹映射开关、预览表、执行结果与历史；
6. 三端检查全绿，文档同步。

## 9. 边界与风险

- 导入只写 D1 `my_repositories` / `categories` / `tags` / `repo_tags`，**不触发 VPS 摘要 / 向量化**；
  导入后的摘要与向量需由既有同步 / 摘要任务补齐（M1-13、M5-01）；
- Star / 语言等元数据以导入文件为准，可能与 GitHub 当前值不一致；后续由 M1-07 增量同步纠正；
- 分类为全局数据，导入只按名称复用 / 新建顶级分类，不处理多级文件夹层级；
- 书签 HTML 的文件夹名可能含浏览器默认目录（书签栏 / 其他书签），默认忽略这些根目录；
- 全局主键限制导致的跨用户冲突无法在本期解决，已在 open-questions 记录。

## 10. 执行结果（2026-10-22）

- edge：`src/import/parse.ts`（JSON / CSV / 书签 HTML 解析与计划）、`src/routes/import.ts`（预览 / 执行 / 历史）、
  `migrations/0022_data_import.sql`、`scripts/import-helpers.test.mjs`（12 用例）、
  `scripts/import-route.test.mjs`（7 用例，含重复执行幂等）；
- admin：`features/import/*`（类型 / API / 工具 / 页面 / 6 用例）、`routes/_authenticated/import/index.tsx`、侧边栏入口；
- 文档：`guides/data-import.md`、架构总览 3.35、数据模型 3.26、D1 Schema、backlog / roadmap / task-planning / Q36；
- 检查：edge typecheck + 233 用例、admin lint + build + 255 用例、vps 549 用例、`git diff --check` 全绿。
