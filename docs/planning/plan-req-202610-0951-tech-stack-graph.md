# 实施计划 · REQ-202610-0951 技术栈图谱视图（语言 / 框架聚合）

> 需求：REQ-202610-0951（backlog M6-04）｜ 分支：`feat/req-202610-0951-tech-stack-graph`
> 依赖：M1-11（仓库分类 / 标签 / 语言筛选）｜ 基线：`feat/req-202610-0947-m5-acceptance` @ `f5f664e`

## 1. 现状与缺口

- `my_repositories` 已有 `language` 字段，标签体系（`tags` / `repo_tags`）也已落地，但后台没有一处把「我主要用什么语言、常用哪些框架、哪些组合最常见」聚合起来；
- 仓库列表只能逐条查看，无法回答「TypeScript 项目里我最常用 React 还是 Next.js」「Python 侧是否集中在 FastAPI」这类技术画像问题；
- 热榜表虽有 `tech_stack` 文本，但收藏仓库没有 `tech_stack` / `topics` 列，直接依赖结构化技术栈字段会引入迁移与回填成本；
- M6-07「依赖分析」、M9-01「个人技术画像」都需要一个可复用的语言 / 框架聚合口径，本需求先提供只读基线。

## 2. 方案总览

```
admin /tech-stack
  → GET /api/tech-stack（Cookie 会话，登录态）
  → edge 读取 D1：my_repositories + repo_tags / tags（按 user_id 隔离）
  → 语言归一 + 框架启发式识别（标签精确命中 → 简介 / 摘要关键词）
  → 聚合：语言榜、框架榜、语言 × 框架关系图（Top 8 × Top 16）
  → admin 渲染 KPI、径向关系图、语言条形榜、框架排行与组合洞察
```

设计原则：

1. **只读聚合、不新增表**：全部在 edge 读时计算，不引入迁移与回填任务；
2. **账号隔离**：SQL 一律带 `user_id = ?`，标签查询 join `my_repositories` 双重限定；
3. **纯函数聚合**：`buildTechStackGraph` 不访问 D1 / 网络，便于单元测试与后续复用；
4. **启发式可解释**：框架识别规则集中在 `catalog.ts` 别名表，后续可平滑替换为 LLM 打标或 `topics` 字段。

## 3. 接口契约

`GET /api/tech-stack`（需登录；未登录返回 `401 {error:"unauthorized"}`）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `summary.totalRepos` | number | 当前账号收藏仓库总数 |
| `summary.withLanguage` | number | `language` 非空的仓库数 |
| `summary.withFramework` | number | 至少识别出一个框架的仓库数 |
| `summary.languageCount` / `frameworkCount` | number | 去重后的语言 / 框架数量 |
| `summary.topLanguage` / `topFramework` | string \| null | 仓库数最多的语言 / 框架 |
| `summary.coverage` | number | 语言或框架至少识别其一的仓库占比（0–100，一位小数） |
| `summary.totalStars` | number | 全部收藏仓库 Star 合计 |
| `languages[]` | array | `name` / `repoCount` / `starCount` / `share` / `frameworks`（Top 6） |
| `frameworks[]` | array | `name` / `category` / `repoCount` / `starCount` / `share` / `languages` |
| `graph.nodes[]` | array | `id`（`lang:` / `fw:` 前缀）/ `label` / `kind` / `category?` / `weight` |
| `graph.links[]` | array | `source` / `target` / `weight`（同语言仓库中出现该框架的次数） |
| `generatedAt` | string | ISO 时间戳 |

口径说明：

- `share` 统一以**全部收藏仓库数**为分母，便于横向比较覆盖率；
- 同一仓库同一框架只计一次；标签命中优先于文本命中；
- 图谱仅保留 Top 8 语言与 Top 16 框架，连线只保留两端都在图中的组合，避免节点过多不可读；
- 文本匹配使用词边界，避免 `react` 命中 `reactive`、`vite` 命中 `invite`。

## 4. 代码改动

| 位置 | 内容 |
| --- | --- |
| `edge/src/tech-stack/catalog.ts` | 框架别名表（约 70 项，含分类与别名） |
| `edge/src/tech-stack/aggregate.ts` | 语言归一、框架识别、聚合与图谱构建（纯函数） |
| `edge/src/routes/tech-stack.ts` | `GET /api/tech-stack` 路由与 D1 查询 |
| `edge/src/index.ts` | 挂载 `/api/tech-stack` |
| `edge/scripts/tech-stack-helpers.test.mjs` | node:test 覆盖归一化 / 匹配 / 聚合 / 空数据 |
| `admin/src/features/tech-stack/api.ts` | 响应类型、演示数据、`fetchWithFallback` |
| `admin/src/features/tech-stack/utils.ts` | 语言折叠、百分比、Top 组合、径向布局 |
| `admin/src/features/tech-stack/components/tech-stack-graph.tsx` | SVG 径向图（悬停 / 聚焦 / 图例 / 无障碍标签） |
| `admin/src/features/tech-stack/index.tsx` | 页面：KPI、关系图、语言分布、框架排行、组合洞察、空状态 |
| `admin/src/features/tech-stack/tech-stack.test.ts` | Vitest 覆盖工具函数与布局 |
| `admin/src/routes/_authenticated/tech-stack/index.tsx` | 文件式路由 |
| `admin/src/components/layout/data/sidebar-data.ts` | 「开源资产」下新增「技术栈图谱」 |

## 5. 可视化设计

- 形式：**径向关系图**表达语言与框架的从属 / 共现关系，**条形榜**表达语言仓库数量级，**表格**给出完整框架明细；
- 颜色：语言蓝 `#2a78d6`（深色 `#3987e5`），框架橙 `#eb6834`（深色 `#d95926`）；两色经 dataviz 校验器在明暗两种模式下通过对比度与色盲分离检查；
- 文字使用前景 / 弱化文本色，不跟随系列色；节点均有文字标签 + `<title>`，颜色不是唯一识别通道；
- 条形长度按最高语言归一，右侧百分比为真实占比，避免误读；
- 空数据（0 仓库）显示引导状态，不渲染空图。

## 6. 测试与验收

| 层 | 用例 |
| --- | --- |
| edge 单元 | 别名归一、语言别名、标签命中、文本词边界、聚合占比 / 覆盖率 / Top 组合、空结构 |
| admin 单元 | 语言折叠「其他」、百分比 / 紧凑数字、Top 组合排序、径向布局内外圈与连线坐标 |
| admin 构建 | `npm run lint`、`npm run build`（含 routeTree 生成）、`npm run test` |
| edge 回归 | `npm run typecheck`、`npm test` |

验收标准：

1. 登录用户访问 `/tech-stack` 能看到 KPI、语言分布、框架排行与关系图；0 仓库时显示空状态；
2. 接口只返回当前用户数据，未登录 401；
3. 语言 / 框架 / 组合计数与 D1 数据一致，`share` / `coverage` 口径符合第 3 节；
4. 明暗模式下图例、标签、悬停提示均可用，键盘可聚焦节点；
5. 三端检查全绿，文档同步更新。

## 7. 风险与后续

- **启发式误判**：简介中出现框架名但仓库并未使用（如「对比 React 与 Vue」）会被计入；当前以标签优先 + 词边界降低误报，后续可接 M7-01 自动打标或 GitHub `topics` 字段；
- **无 `tech_stack` 列**：本需求刻意不迁移，若后续 M6-07 依赖分析需要结构化依赖，再评估新增 `repo_tech_stack` 表；
- **大数据量**：单用户仓库数预计在千级以内，全量读取后内存聚合可接受；若后续支持组织级账号，需改为 SQL 预聚合 + 分页；
- **Top N 截断**：图谱只展示 Top 8 / 16，长尾在语言榜「其他」与框架表中仍可查看完整列表。
