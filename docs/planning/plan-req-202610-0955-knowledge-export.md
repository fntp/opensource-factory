# 实施计划 · REQ-202610-0955 知识库导出（Markdown / JSON / Obsidian）

> 需求：REQ-202610-0955（backlog M6-08）｜ 分支：`feat/req-202610-0955-knowledge-export`
> 依赖：M9-04（全量导出与归档，尚未落地）｜ 基线：`v1.0.0` @ `53ab76f`

## 1. 现状与缺口

- 收藏仓库、分类、标签与 README 摘要都已在 D1 中，但后台只能逐页浏览，无法一次性带走；
- `docs/requirements/backlog.md` 的 M6-08 要求同时支持 Markdown / JSON / Obsidian 三种格式，
  依赖 M9-04 的「全量导出与归档（备份格式规范）」，而 M9-04 仍在待排期；
- 用户换工具、做个人知识库或二次分析时，需要可读（Markdown）、可机读（JSON）、
  可直接进 Obsidian 仓库（frontmatter + 双链 + ZIP）三种出口；
- 导出属于**只读聚合**，不新增表、不写 D1，不应影响现有仓库 / 分类 / 标签链路。

## 2. 方案总览

```
admin /export（知识库导出页）
  → GET /api/export/knowledge/summary（登录态，统计卡）
  → GET /api/export/knowledge?format=markdown|json|obsidian&includeSummary=1&groupBy=category
  → edge 读取 D1：my_repositories + categories + tags / repo_tags（user_id 隔离）
  → 纯函数构建三种导出物：
       JSON      → openfactory.knowledge.v1 结构化文档
       Markdown  → 单文件知识库（目录 + 分类分组 + 仓库条目）
       Obsidian  → ZIP 仓库（README 索引 + 分类笔记 + 仓库笔记，YAML frontmatter / 双链）
  → Content-Disposition 附件下载
```

设计原则：

1. **只读、无迁移**：不新增 D1 表与列，全部读时生成；
2. **账号隔离**：SQL 一律 `r.user_id = ?`，标签 join 也限定该用户的仓库；
3. **纯函数可测**：构建逻辑放 `edge/src/export/`，不依赖 D1 / 网络，node:test 直接覆盖；
4. **零依赖 ZIP**：Obsidian 包使用 store（不压缩）方式的最小 ZIP writer，避免为一次性导出引入 npm 依赖；
5. **格式即契约**：JSON Schema 与目录布局写入 `docs/guides/knowledge-export.md`，作为 M9-04 的格式基线。

## 3. 接口契约

### 3.1 `GET /api/export/knowledge/summary`

需登录；未登录 `401 {error:"unauthorized"}`。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `totalRepos` | number | 当前用户收藏仓库总数 |
| `withSummary` | number | 有 README 摘要的仓库数 |
| `categoryCount` | number | 出现过的分类数（含「未分类」） |
| `tagCount` | number | 去重标签数 |
| `totalStars` | number | Star 合计 |
| `generatedAt` | string | ISO 时间戳 |

### 3.2 `GET /api/export/knowledge`

查询参数：

| 参数 | 取值 | 默认 | 说明 |
| --- | --- | --- | --- |
| `format` | `markdown` / `json` / `obsidian` | `markdown` | 非法值回退 `markdown` |
| `includeSummary` | `1` / `0` | `1` | 是否包含 README 摘要 |
| `groupBy` | `category` / `none` | `category` | Markdown / Obsidian 的分组方式 |

响应：

- `json` → `application/json; charset=utf-8`，附件名 `openfactory-knowledge-<YYYY-MM-DD>.json`；
- `markdown` → `text/markdown; charset=utf-8`，附件名 `openfactory-knowledge-<YYYY-MM-DD>.md`；
- `obsidian` → `application/zip`，附件名 `openfactory-obsidian-vault-<YYYY-MM-DD>.zip`；
- 统一 `Cache-Control: no-store`。

JSON 顶层结构（schema v1）：

```json
{
  "schema": "openfactory.knowledge.v1",
  "version": 1,
  "generatedAt": "2026-10-22T10:00:00.000Z",
  "generator": { "name": "OpenFactory", "url": "https://github.com/fntp/opensource-factory" },
  "user": { "login": "fntp", "name": "fntp" },
  "stats": { "totalRepos": 12, "withSummary": 9, "categories": 4, "tags": 18, "totalStars": 12345 },
  "categories": [{ "id": "cat-1", "name": "AI/LLM", "parentId": null, "repoCount": 5 }],
  "tags": [{ "name": "llm", "count": 3 }],
  "repositories": [
    {
      "id": "owner/repo",
      "fullName": "owner/repo",
      "platform": "github",
      "description": "…",
      "summary": "…",
      "language": "TypeScript",
      "stars": 128,
      "forks": 12,
      "categoryId": "cat-1",
      "category": "AI/LLM",
      "tags": ["llm"],
      "url": "https://github.com/owner/repo",
      "createdAt": "2026-10-01 08:00:00",
      "updatedAt": "2026-10-20T08:00:00Z"
    }
  ]
}
```

## 4. 三种格式

### 4.1 Markdown

- YAML frontmatter（title / generator / generatedAt / repoCount）；
- 统计引言 + 目录（分类锚点）；
- 每个分类一节，仓库按 Star 降序：标题链接、语言 / Star / 标签行、简介、摘要；
- 未分类仓库归入「未分类」；`groupBy=none` 时全部放在「全部项目」一节；
- 文本转义 `[]()#*_|` 等 Markdown 控制字符，保证标题 / 标签不破坏结构。

### 4.2 Obsidian

ZIP 目录：

```
README.md                       # 索引：统计 + 分类双链 + 最近更新
10-项目/<分类>/<owner>--<repo>.md  # 仓库笔记（frontmatter + 摘要 + 链接）
20-分类/<分类>.md                # 分类笔记，列出 [[owner--repo|owner/repo]]
```

仓库笔记 frontmatter：

```yaml
---
title: "owner/repo"
aliases: ["repo"]
tags: ["openfactory", "lang/typescript", "tag/llm", "cat/ai-llm"]
category: "AI/LLM"
language: "TypeScript"
stars: 128
forks: 12
platform: "github"
repo: "owner/repo"
url: "https://github.com/owner/repo"
created: "2026-10-01"
updated: "2026-10-20"
---
```

- 标签名做 Obsidian 合法化：小写、空格转 `-`、去除 `# | [ ]` 等字符；
- 分类 / 文件名做文件系统安全化（保留中文，替换 `/ \ : * ? " < > |`）；
- 同名仓库以 `owner--repo` 保证唯一。

## 5. 代码改动

| 位置 | 内容 |
| --- | --- |
| `edge/src/export/build.ts` | 数据类型、归一化、Markdown / JSON / Obsidian 构建、ZIP writer |
| `edge/src/routes/export.ts` | summary + export 路由、D1 查询与附件响应 |
| `edge/src/index.ts` | 挂载 `/api/export` |
| `edge/scripts/export-helpers.test.mjs` | 纯函数 / ZIP 结构 / 统计单测 |
| `admin/src/features/export/api.ts` | 类型、演示数据、summary 请求、下载封装 |
| `admin/src/features/export/utils.ts` | 格式元信息、文件名、演示内容、ZIP 打包 |
| `admin/src/features/export/index.tsx` | 导出页：统计卡、格式卡、选项、下载、空状态 |
| `admin/src/features/export/export.test.ts` | 工具函数与演示内容测试 |
| `admin/src/routes/_authenticated/export/index.tsx` | 文件式路由 |
| `admin/src/components/layout/data/sidebar-data.ts` | 「开源资产」新增「知识库导出」 |
| `docs/guides/knowledge-export.md` | 用户指南 + 格式规范（M9-04 基线） |
| `docs/architecture/overview.md` | 导出流与接口表 |
| `docs/architecture/data-model.md` | 说明只读聚合、不新增表 |
| `docs/requirements/backlog.md` / `roadmap.md` / `task-planning.md` | M6-08 状态与交付记录 |
| `docs/README.md` / `admin/README.md` / `edge/README.md` | 索引与页面 / 接口说明 |

## 6. 测试与验收

| 层 | 用例 |
| --- | --- |
| edge 单元 | 格式 / 参数归一化、Markdown 结构、JSON schema、Obsidian 文件清单与 frontmatter、ZIP 中央目录、空数据 |
| edge 回归 | `npm run typecheck`、`npm test` |
| admin 单元 | 格式元信息、文件名、演示 Markdown / JSON / ZIP、统计格式化 |
| admin 构建 | `npm run lint`、`npm run build`（含 routeTree 生成）、`npm run test` |
| vps 回归 | `.venv/bin/pytest -q`（本需求未改 vps，仍跑全量确认无回归） |

验收标准：

1. 登录用户访问 `/export` 能看到统计、三种格式与选项，并能下载对应文件；
2. 未登录调用导出接口返回 401；导出只包含当前用户仓库；
3. JSON 可被 `JSON.parse`，Markdown 目录 / 分类 / 条目完整，Obsidian ZIP 可被标准解压工具打开且笔记含 frontmatter；
4. `includeSummary=0` 时三种格式均不出现摘要正文；
5. 三端检查全绿，文档同步更新。

## 7. 风险与后续

- **M9-04 未落地**：本需求先定义 `openfactory.knowledge.v1` 作为知识库格式；M9-04 做全量归档时复用该 schema，并补充备份元数据（校验和 / 保留策略）；
- **大仓库量**：单用户千级仓库时 JSON / Markdown 体积可控；Obsidian ZIP 为 store 模式，体积接近原文，后续可换压缩实现；
- **文件名冲突**：`owner--repo` 与分类名安全化已处理常见字符，极端同名仍可能覆盖，后续可加短哈希后缀；
- **摘要缺失**：无摘要仓库只输出简介，界面统计 `withSummary` 提示覆盖率。
