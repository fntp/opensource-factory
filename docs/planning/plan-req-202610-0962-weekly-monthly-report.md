# 实施计划 · REQ-202610-0962 每周 / 月度精选报告（自动生成）

> 需求：REQ-202610-0962（backlog M7-03）｜ 分支：`feat/req-202610-0962-weekly-monthly-report`
> 依赖：M4-01 每日评估（已落地，`recommendations` 带 `quality_score` / 评估状态）
> 目标：按周 / 按月自动汇总当前用户的收藏、推荐与热榜数据，生成可回看、可下载的精选报告。

## 1. 现状与缺口

- 收藏库、分类 / 标签、推荐与热榜数据都已落在 D1，但没有任何「周期回顾」视图；
- 用户只能逐条浏览，无法回答「这一周我收藏了什么、哪些项目值得回看、热榜上什么在涨」；
- M4-01 已产出带质量分的推荐，但结果只在推荐 / 通知链路消费，没有被沉淀为周期报告；
- 报告需要按用户隔离，而 VPS 的 `my_repositories` 是全局镜像、没有 `user_id`，不适合作为报告数据源。

## 2. 方案总览

```
Cloudflare Cron（周一 07:30 / 每月 1 日 07:40，Asia/Shanghai）
  → edge scheduled handler
     → 枚举 D1 users，按「上一个完整周期」逐用户生成
        ├─ my_repositories（user_id 过滤）
        ├─ repo_tags / tags（join 当前用户仓库）
        ├─ categories（分类名映射）
        ├─ recommendations（user_id + 周期内 + 非 dismissed / expired）
        └─ trending_snapshots（周期内 star_delta / 排名）
     → 纯函数 buildReport：统计、分节、摘要、Markdown
     → upsert curated_reports（user_id + kind + period_start 唯一）

admin /reports
  → GET /api/reports?kind=weekly|monthly（登录态，缺失时惰性生成当前周期）
  → GET /api/reports/:id（详情）
  → GET /api/reports/:id/markdown（下载）
  → POST /api/reports/generate（立即生成当前周期）
```

设计原则：

1. **只读聚合、按用户隔离**：SQL 一律带 `user_id = ?`，报告只包含当前用户收藏；
2. **纯函数生成**：统计 / 分节 / 摘要 / Markdown 全部在 `edge/src/reports/generate.ts`，不依赖 D1 与网络，node:test 直接覆盖；
3. **周期可解释**：周报为自然周（周一至周日），月报为自然月；定时任务生成上一个完整周期，页面首次访问惰性生成当前周期；
4. **幂等**：`(user_id, kind, period_start)` 唯一，重复生成走 upsert，不产生重复报告；
5. **不新增 VPS 表**：报告数据全部来自 D1 既有表，只新增 `curated_reports` 一张 D1 表。

## 3. 数据模型

`curated_reports`（D1 迁移 `0014_curated_reports.sql`）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | TEXT PK | 稳定 id：`rpt_<kind>_<periodStart>_<userHash>` |
| `user_id` | TEXT | 用户 id |
| `kind` | TEXT | `weekly` / `monthly` |
| `period_start` / `period_end` | TEXT | `YYYY-MM-DD`（UTC） |
| `title` | TEXT | 报告标题 |
| `summary` | TEXT | 中文摘要 |
| `stats` | TEXT | 统计 JSON |
| `sections` | TEXT | 分节 JSON（新增收藏 / 收藏之星 / 推荐 / 热榜） |
| `markdown` | TEXT | 预渲染 Markdown（下载 / 归档） |
| `status` | TEXT | `ready` / `empty` |
| `generated_at` | TEXT | ISO 时间 |
| 唯一索引 | `(user_id, kind, period_start)` | 同一用户同一周期只保留一份 |

## 4. 接口

| 端点 | 方法 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| `/api/reports` | GET | 登录态 | 报告列表（`kind=all\|weekly\|monthly`、`limit`、`ensure=0/1`） |
| `/api/reports/:id` | GET | 登录态 | 报告详情 |
| `/api/reports/:id/markdown` | GET | 登录态 | 下载 Markdown |
| `/api/reports/generate` | POST | 登录态 | 立即生成当前周期（`kind`） |
| `/api/internal/reports/generate` | POST | `X-Internal-Token` | 定时 / 运维批量生成（`kind`、`userId?`、`mode=current\|previous`） |

## 5. 报告内容

- 数据概览：收藏总数、本期新增、Star 合计 / 新增、分类 / 语言数、推荐 / 热榜条数；
- 本期新增收藏：周期内 `my_repositories.created_at` 命中的仓库，按 Star 降序；
- 收藏库之星：当前收藏中 Star 最高的仓库；
- 推荐关注：周期内 `recommendations`（排除 dismissed / expired / saved），按匹配度 `score` 排序；
- 热榜精选：周期内 `trending_snapshots` 按 `star_delta` 排序；
- 摘要与 Markdown 由确定性模板生成，不依赖 LLM / 网络，测试可稳定断言。

## 6. 交付物

| 文件 | 说明 |
| --- | --- |
| `edge/src/reports/generate.ts` | 周期解析、统计、分节、摘要、Markdown 纯函数 |
| `edge/src/routes/reports.ts` | 登录态 / 内部报告路由与 D1 读写 |
| `edge/src/index.ts` | 挂载路由 + Cron scheduled handler |
| `edge/wrangler.toml` | 周报 / 月报 Cron 触发 |
| `edge/migrations/0014_curated_reports.sql` | 报告表 |
| `edge/scripts/reports-helpers.test.mjs` | 纯函数用例 |
| `edge/scripts/reports-route.test.mjs` | 路由 / 鉴权 / 幂等用例 |
| `admin/src/features/reports/` | API、工具函数、报告页、演示数据、Vitest |
| `admin/src/routes/_authenticated/reports/index.tsx` | 文件式路由 |
| `admin/src/components/layout/data/sidebar-data.ts` | 「开源资产」新增「精选报告」 |
| 文档 | 本计划、架构总览、数据模型、D1 schema、backlog、roadmap、task-planning、README |

## 7. 测试与验收

| 层 | 用例 |
| --- | --- |
| edge 单元 | 周 / 月周期（当前 / 上一周期）、统计口径、分节排序、空数据、Markdown 结构 |
| edge 路由 | 未登录 401、列表惰性生成、详情 404 / 越权隔离、手动生成、内部令牌 503 / 401 / 200 |
| admin 单元 | 报告类型 / 状态文案、数字与日期格式化、Mock 数据筛选 |
| 回归 | edge `npm run typecheck` + `npm test`；admin `npm run lint` + `npm run build` + `npm run test`；vps `pytest -q` |

验收标准：

1. 登录用户访问 `/reports` 能看到周报 / 月报列表与详情、统计卡、分节内容；
2. 没有历史报告时自动生成当前周期，不出现空白页；
3. 周报 / 月报可按类型切换，空数据显示明确的空状态；
4. 报告只包含当前用户数据；未登录接口 401；
5. Markdown 可下载且包含标题、统计与分节；
6. 定时任务按周一 / 每月 1 日生成上一周期报告，重复触发幂等；
7. 三端检查全绿，文档同步更新。

## 8. 实施结果（2026-10-22）

- 新增 D1 迁移 `0014_curated_reports.sql`，`docs/assets/d1-schema.sql` 同步；
- `edge/src/reports/generate.ts` 实现周期解析、统计、四分节、摘要与 Markdown 纯函数；
- `edge/src/routes/reports.ts` 实现列表 / 详情 / Markdown / 手动生成 / 内部批量生成，全部按 `user_id` 隔离；
- `edge/src/index.ts` 挂载路由并新增 `scheduled` handler，`wrangler.toml` 配置周报 / 月报 Cron；
- admin 新增 `/reports` 页面：周报 / 月报切换、报告归档、统计卡、分节内容、空状态、立即生成与 Markdown 下载；
- 测试结果：edge 103 用例、admin 151 用例、vps 460 用例全部通过；edge `tsc --noEmit`、admin `lint` / `build` 通过；
- 上线待办：部署前执行远端迁移 `wrangler d1 migrations apply opensource-factory --remote`，并 `wrangler deploy` 使 Cron 生效。

## 9. 风险与后续

- **周期口径**：周报按自然周（周一至周日）、月报按自然月；如需「滚动 7 / 30 天」可在后续配置化；
- **报告体量**：单用户每期最多约 20 条精选，Markdown 体积可控；历史报告默认保留全部，后续可加保留策略；
- **推荐覆盖率**：没有评估推荐时报告只包含收藏 / 热榜，摘要会标注数据来源；
- **送达渠道**：本期只做站内查看与 Markdown 下载，不主动推送；后续可复用 M4 通知 / Email 通道推送报告链接。
