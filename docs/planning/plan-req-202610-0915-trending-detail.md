# 实施计划 · REQ-202610-0915 热榜详情页（摘要 + 元信息 + 一键收藏）

> 需求：REQ-202610-0915（backlog M2-07）｜ 分支：`feat/req-202610-0915-trending-detail`
> 依赖：M2-04 中文摘要（摘要字段消费方）、M2-06 热榜页联动（列表入口）
> 日期：2026-10-22

## 1. 目标

在「每日热榜」列表基础上补齐详情闭环：

1. **详情页**：展示项目摘要、完整元信息（总 Star / 今日 Star / 主语言 / 技术栈 / 平台 / 抓取日期 / 仓库地址）；
2. **一键收藏**：详情页可直接把热榜项目收录到当前用户的「我的仓库」，支持取消收藏与已收藏状态回显；
3. **降级可用**：VPS / D1 数据缺失时页面仍有明确空态与错误重试，不因单一依赖失败白屏；
4. **契约稳定**：列表接口保持向后兼容，仅追加可选字段。

## 2. 现状与缺口

- admin `features/trending` 只有静态列表，条目不可点击，无详情页；
- edge `GET /api/trending` 只返回列表，无单条详情与收藏写接口；
- `trending_repositories` 没有摘要列，详情页无法展示 M2-04 产出的中文摘要；
- `my_repositories` 只有同步写入路径，没有「从热榜收藏」的入口；
- VPS 热榜模型缺少 `owner` / `language` / `stars` 列，详情元信息只能依赖 D1。

## 3. 方案

### 3.1 数据模型

- D1 迁移 `edge/migrations/0008_trending_detail.sql`：
  - `ALTER TABLE trending_repositories ADD COLUMN readme_summary TEXT`（M2-04 摘要落点；为空时详情页回退描述）；
  - 新增 `(platform, stars_today DESC)` 组合索引，服务列表/详情查询。
- VPS `TrendingRepository` 增加 `owner` / `language` / `stars` / `readme_summary`；
  `init_db()` 对既有 SQLite 库做幂等补列（`ALTER TABLE ... ADD COLUMN`，列已存在则跳过），
  兼容旧库不重建。
- `docs/assets/d1-schema.sql` 同步新列。

### 3.2 edge API

| 端点 | 方法 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| `/api/trending/:owner/:name` | GET | 可选 | 单条详情；登录时回显 `isFavorited` |
| `/api/trending/:owner/:name/favorite` | POST | 必须 | 一键收藏到 `my_repositories`（幂等） |
| `/api/trending/:owner/:name/favorite` | DELETE | 必须 | 取消收藏（仅删除当前用户的行） |

详情响应：

```ts
TrendingRepoDetail {
  id: string
  platform: string
  owner: string
  name: string
  description: string | null
  language: string | null
  stars: number
  starsToday: number
  url: string
  techStack: string[]
  summary: string | null
  summarySource: 'readme' | 'description' | 'tech' | 'empty'
  crawledAt: string | null
  isFavorited: boolean
}
```

收藏写入字段：`id=owner/repo`、`platform`、`name`、`description`、`html_url`、`stars`、
`language`、`readme_summary`（摘要优先，回退描述）、`user_id`、`owner`、`forks=0`、
`updated_at/synced_at=当前时间`。使用 `INSERT OR IGNORE` 保证幂等；若同 id 已属于其他用户，
返回 409 `repo_exists`，不覆盖他人资产。

### 3.3 VPS API

`GET /api/trending/{repo_id:path}`：

- 查本地 `trending_repositories`，不存在返回 404；
- 摘要优先级：`readme_summary` → `description` → 技术栈提示 → 空；
- 返回 `owner/language/stars/tech_stack/summary/summary_source/crawled_at`，供 edge 详情联调与本地直查；
- 列表 `GET /api/trending` 追加可选字段，保持原字段不变。

### 3.4 admin

- 新增路由 `/_authenticated/trending/$owner/$name` 与 `features/trending/detail.tsx`：
  - 顶部返回热榜、仓库外链、收藏/取消收藏按钮；
  - 摘要卡片（标注来源：README 摘要 / 项目描述 / 技术栈提示）；
  - 元信息网格：总 Star、今日 Star、主语言、平台、抓取日期、技术栈；
  - 加载骨架、404/错误态与重试；
  - 收藏成功后 toast，并失效 `['trending']` 查询以刷新列表状态。
- 列表页：仓库名改为详情页链接，行尾增加「详情」按钮；保留演示数据兜底。
- `features/trending/api.ts`：新增详情/收藏/取消收藏客户端与演示数据实现；
  `features/trending/detail.ts` 抽出纯函数（路径拼接、摘要回退、元信息项）便于单测。

## 4. 文件清单

- `edge/migrations/0008_trending_detail.sql`、`docs/assets/d1-schema.sql`
- `edge/src/trending/detail.ts`、`edge/src/routes/trending.ts`、`edge/src/types.ts`
- `vps/app/models.py`、`vps/app/db.py`、`vps/app/schemas.py`、`vps/app/api/trending.py`、`vps/app/tasks/jobs.py`
- `vps/tests/test_trending_detail.py`
- `admin/src/features/trending/{api.ts,detail.ts,detail.tsx,detail.test.ts,index.tsx}`
- `admin/src/routes/_authenticated/trending/$owner/$name.tsx`
- `docs/architecture/overview.md`、`docs/architecture/data-model.md`、`docs/planning/task-planning.md`、`docs/requirements/backlog.md`
- `edge/README.md`、`vps/README.md`

## 5. 验证计划

| 检查 | 命令 |
| --- | --- |
| edge 类型 | `cd edge && npm run typecheck` |
| vps 单测 | `cd vps && .venv/bin/pytest -q` |
| admin 静态 | `cd admin && npm run lint && npm run build` |
| admin 单测 | `cd admin && npm run test` |
| 空白检查 | `git diff --check` |

新增用例覆盖：VPS 详情 404 / 摘要回退优先级 / 元信息字段；admin 详情路径、摘要回退与元信息项。

## 6. 风险与边界

1. **M2-04 尚未合并**：详情页消费 `readme_summary`，为空时回退描述并明确标注来源；摘要生成仍由 M2-04 承接。
2. **M2-06 尚未合并**：本页按 `owner/name` 直达，不依赖日期/语言筛选参数；列表入口保持兼容。
3. **迁移编号**：0007 已被 M2-06 计划占用，本需求使用 0008；合并时如冲突按实际分支重排。
4. **多用户主键**：`my_repositories.id` 为 `owner/repo` 全局主键；收藏遇到他人同 id 行时返回 409，不做覆盖。
5. **生产部署**：需在 D1 执行迁移 0008；VPS 旧库由 `init_db()` 幂等补列。
