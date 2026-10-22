# 实施计划 · REQ-202610-0964 Star 趋势与洞察视图

> 需求：REQ-202610-0964（backlog M7-05）｜ 分支：`feat/req-202610-0964-star-trend-insights`
> 依赖：M2-05 热榜按日快照（`trending_snapshots`）｜ 基线：`affd2e5`（M6 集成分支）

## 1. 现状与缺口

- M2-05 已把每日热榜写入 `trending_snapshots`，包含 `stars` / `star_delta` / `rank_delta` /
  `appearances` / `is_new` / `trend` 等趋势字段，但只有热榜详情页的单仓库历史接口
  （`GET /api/trending/history`），没有跨仓库的趋势聚合与洞察视图；
- 仪表盘里的「Star 增长趋势」仍是静态演示图，不能反映真实快照；
- 用户无法回答「最近哪些项目 Star 涨得最快」「我的收藏里谁在增长」「哪个语言在升温」；
- 快照数据只覆盖上过热榜的项目，收藏库中未上榜仓库暂无历史，页面需要明确覆盖率而不是伪造曲线。

## 2. 方案总览

```
admin /star-trends
  → GET /api/star-trends?days=30&scope=trending|my&language=
    → edge（登录态）
       ├─ scope=trending：读取 trending_snapshots 最近 N 天
       ├─ scope=my：读取当前用户 my_repositories（id / stars / language），
       │              按 repo_id 分片查询这些仓库的快照
       ├─ 纯函数 buildStarTrends：
       │    ├─ 按日聚合：追踪仓库数 / 总 Star / 每日净增 / 新上榜数
       │    ├─ 按仓库聚合：区间净增、增长率、连续上榜、sparkline
       │    ├─ Top Movers / 新上榜 / 语言贡献
       │    └─ 确定性洞察文案（增长冠军 / 语言升温 / 头部集中 / 降温提醒）
       └─ 返回 summary / series / topMovers / newEntries / languages / insights
  → admin 渲染 KPI、SVG 趋势图、洞察卡、Top Movers 表、语言贡献条、新上榜列表
```

设计原则：

1. **只读聚合、不新增表**：复用 M2-05 的 `trending_snapshots`，不引入迁移；
2. **账号隔离**：`scope=my` 的仓库白名单来自 D1 `my_repositories WHERE user_id = ?`，
   快照查询按白名单分片，不把其他用户仓库带入结果；
3. **纯函数可测**：聚合 / 排序 / 洞察生成全部放 `edge/src/insights/star-trends.ts`，
   不依赖 D1 / 网络，node:test 直接覆盖；
4. **不伪造历史**：`scope=my` 明确返回 `portfolioRepos` 与 `coverage`，只对真正有快照的仓库画曲线；
5. **优雅降级**：无快照 / 无收藏时返回结构化空态，admin 展示引导而不是空白页；
6. **确定性洞察**：不依赖 LLM，文案由实际数据生成，测试可稳定断言。

## 3. 接口契约

### 3.1 `GET /api/star-trends`（登录态）

| 参数 | 取值 | 默认 | 说明 |
| --- | --- | --- | --- |
| `days` | 1–365 | 30 | 统计窗口（含今天向前 N 天） |
| `scope` | `trending` / `my` | `trending` | 热榜洞察 / 我的收藏 |
| `language` | 语言名（≤64 字） | — | 可选语言过滤（仅对快照行生效） |

未登录返回 `401 {error:"unauthorized"}`。

响应：

| 字段 | 说明 |
| --- | --- |
| `scope` / `period` | 范围与窗口（`days` / `startDate` / `endDate` / `snapshotDays`） |
| `summary.trackedRepos` | 窗口内有快照的仓库数 |
| `summary.totalStars` | `trending`：最新快照总 Star；`my`：收藏库当前总 Star |
| `summary.starGain` | 窗口内追踪仓库的净增 Star（首末快照差之和） |
| `summary.averageDailyGain` | 净增 / (快照日数 - 1)（单日快照按 1 计） |
| `summary.fastestGrowing` | 增长最快的仓库（`repoId` / `name` / `gain` / `growthRate`） |
| `summary.newEntries` | 新上榜仓库数 |
| `summary.risingRepos` / `fallingRepos` | 净增为正 / 为负的仓库数 |
| `summary.portfolioRepos` / `coverage` | 仅 `my`：收藏总数与有快照的覆盖率（0–100，一位小数） |
| `series[]` | `date` / `trackedRepos` / `totalStars` / `starGain` / `newRepos` |
| `topMovers[]` | 净增为正的 Top 10，含 `sparkline[]`、`appearances`、`trend` |
| `newEntries[]` | 新上榜 Top 5（同 mover 结构） |
| `languages[]` | 语言 / 仓库数 / Star 增量 / 贡献占比 / 代表项目 |
| `insights[]` | `kind`（`growth` / `language` / `new` / `concentration` / `cooling`）/ `title` / `description` |
| `generatedAt` | ISO 时间戳 |

## 4. 页面

`/star-trends`（侧边栏「开源资产 → Star 趋势」）：

- 范围切换：热榜洞察 / 我的收藏；窗口 7 / 30 / 90 天；
- KPI 四卡：追踪仓库、最新总 Star、区间净增、日均净增（我的收藏显示覆盖率）；
- SVG 趋势图：每日 Star 净增面积线，带网格、首中末日期与数据点 `<title>`；
- 洞察卡：增长冠军、语言升温、新上榜、头部集中、降温提醒；
- Top Movers 表：排名、仓库、语言、总 Star、区间净增、增长率、sparkline、趋势徽章；
- 语言贡献条：按 Star 增量排序，占比以正增量总和为分母；
- 新上榜列表：卡片式展示 `is_new` 项目；
- 空态：无快照时提示「等待热榜快照积累」；`my` 无收藏时引导去仓库页。

## 5. 交付物

| 文件 | 说明 |
| --- | --- |
| `edge/src/insights/star-trends.ts` | 快照聚合、Top Movers、语言贡献、洞察生成（纯函数） |
| `edge/src/routes/star-trends.ts` | 登录态路由、D1 读取与用户仓库白名单分片 |
| `edge/src/index.ts` | 挂载 `/api/star-trends` |
| `edge/scripts/star-trends.test.mjs` | 聚合 / 排序 / 覆盖率 / 空态 / 洞察单测 |
| `admin/src/features/star-trends/api.ts` | DTO、演示数据、请求封装 |
| `admin/src/features/star-trends/utils.ts` | 数字 / 百分比格式化、折线与 sparkline 坐标 |
| `admin/src/features/star-trends/components/star-trend-chart.tsx` | SVG 面积折线图 |
| `admin/src/features/star-trends/components/sparkline.tsx` | 迷你趋势线 |
| `admin/src/features/star-trends/index.tsx` | 页面：范围 / 窗口、KPI、图表、洞察、Top Movers、语言、新上榜、空态 |
| `admin/src/features/star-trends/star-trends.test.ts` | 格式化、坐标、演示数据一致性 |
| `admin/src/routes/_authenticated/star-trends/index.tsx` | 文件式路由 |
| `admin/src/components/layout/data/sidebar-data.ts` | 「开源资产」新增「Star 趋势」 |
| 文档 | 本计划、架构总览、数据模型、backlog、roadmap、task-planning、open-questions、三端 README |

## 6. 测试与验收

| 层 | 用例 |
| --- | --- |
| edge | 按日聚合、仓库净增 / 增长率、Top Movers 排序、新上榜、语言贡献、洞察文案、`my` 覆盖率、空态、语言过滤 |
| admin | 数字 / 百分比格式化、折线坐标单调性、sparkline 路径、演示数据字段一致性 |
| 构建 | `edge npm run typecheck` + `npm test`；`admin npm run lint` + `npm run build` + `npm run test`；`vps .venv/bin/pytest -q` 回归 |
| 手工 | 打开 `/star-trends`：切换范围 / 窗口、查看 KPI 与图表、确认 Top Movers 与洞察随数据变化；无数据时显示空态 |

验收标准：

1. 登录用户访问 `/star-trends` 能看到真实快照聚合的 KPI、趋势图、Top Movers 与洞察；
2. `scope=my` 只统计当前用户收藏，返回覆盖率且不出现他人仓库；
3. 无快照时页面显示空态，不出现 NaN / 空白图表；
4. 语言过滤与窗口参数生效，非法参数回退默认值；
5. 三端检查全绿，文档同步更新。

## 7. 风险与后续

- **个人收藏历史覆盖不足**：`trending_snapshots` 只记录上过热榜的仓库，未上榜收藏没有历史；
  本期用 `coverage` 明确说明，后续可在 M9-02 / 资产报表中增加「收藏库每日 Star 快照」任务；
- **快照口径**：`star_delta` 是相对上一有效快照的增量，跨窗口首日可能包含窗口外增长；
  汇总净增使用首末快照差，日序列使用 `star_delta`，两者在页面分别标注；
- **数据量**：默认 30 天、单次最多 20000 行；窗口上限 365 天，超量按日期截断，后续可改为 SQL 预聚合；
- **洞察文案**：规则固定、可解释但不具备生成式表达，后续可接 M7-06 模型路由改写。
