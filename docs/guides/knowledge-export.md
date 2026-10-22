# 知识库导出（Markdown / JSON / Obsidian）

> 需求：REQ-202610-0955（backlog M6-08）｜页面：`admin` → 开源资产 → 知识库导出（`/export`）
> 定位：把当前账号的收藏仓库、分类、标签与 README 摘要一次性带走，用于备份、迁移与二次分析。

## 1. 使用方式

1. 登录后台，进入「开源资产 → 知识库导出」；
2. 查看统计卡（项目总数 / 含摘要 / 分类 / 标签 / Star 总数）；
3. 选择导出格式（Markdown / JSON / Obsidian）；
4. 按需设置「包含 README 摘要」与「组织方式（按分类 / 平铺）」；
5. 点击「导出」，浏览器下载对应附件。

导出是**只读聚合**：不新增表、不写 D1，也不会修改仓库、分类或标签。未登录调用接口返回 `401`，导出内容严格按 `user_id` 隔离。

## 2. 接口

### 2.1 `GET /api/export/knowledge/summary`

需登录。返回：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `totalRepos` | number | 当前用户收藏仓库总数 |
| `withSummary` | number | 有 README 摘要的仓库数 |
| `categoryCount` | number | 出现过的分类数（含「未分类」） |
| `tagCount` | number | 去重标签数 |
| `totalStars` | number | Star 合计 |
| `generatedAt` | string | ISO 时间戳 |

### 2.2 `GET /api/export/knowledge`

需登录。查询参数：

| 参数 | 取值 | 默认 | 说明 |
| --- | --- | --- | --- |
| `format` | `markdown` / `json` / `obsidian` | `markdown` | 非法值回退 `markdown` |
| `includeSummary` | `1` / `0` | `1` | 是否包含 README 摘要 |
| `groupBy` | `category` / `none` | `category` | Markdown / Obsidian 的分组方式 |

响应头：

- `Content-Disposition: attachment; filename="<附件名>"`；
- `Cache-Control: no-store`；
- `X-Content-Type-Options: nosniff`。

附件命名：

| 格式 | Content-Type | 文件名 |
| --- | --- | --- |
| Markdown | `text/markdown; charset=utf-8` | `openfactory-knowledge-<YYYY-MM-DD>.md` |
| JSON | `application/json; charset=utf-8` | `openfactory-knowledge-<YYYY-MM-DD>.json` |
| Obsidian | `application/zip` | `openfactory-obsidian-vault-<YYYY-MM-DD>.zip` |

CORS 已暴露 `Content-Disposition`，前端可读取服务端生成的文件名；读取失败时按同一规则本地回退。

## 3. JSON 格式（`openfactory.knowledge.v1`）

```json
{
  "schema": "openfactory.knowledge.v1",
  "version": 1,
  "generatedAt": "2026-10-22T10:00:00.000Z",
  "generator": {
    "name": "OpenFactory",
    "url": "https://github.com/fntp/opensource-factory"
  },
  "user": { "login": "fntp", "name": "fntp" },
  "stats": {
    "totalRepos": 12,
    "withSummary": 9,
    "categories": 4,
    "tags": 18,
    "totalStars": 12345
  },
  "categories": [
    { "id": "cat-1", "name": "AI/LLM", "parentId": null, "repoCount": 5 }
  ],
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

约定：

- `repositories` 按 Star 降序、同 Star 按 `fullName` 升序；
- `categories` 按仓库数降序，「未分类」固定最后；`repoCount` 为该分类下当前用户的仓库数；
- `tags` 按出现次数降序；`tags[].count` 为去重后的仓库数；
- 关闭摘要时 `summary` 字段为 `null`（保留字段，便于消费方稳定解析）；
- 该 schema 同时作为 M9-04「全量导出与归档」的格式基线，后续扩展只加字段、不改语义。

## 4. Markdown 格式

单文件结构：

```markdown
---
title: "我的开源知识库"
generator: "OpenFactory"
generatedAt: "2026-10-22T10:00:00.000Z"
repoCount: 12
---

# 我的开源知识库

> 共 12 个项目 · 4 个分类 · 18 个标签 · ⭐ 12.3k

## 目录

- AI/LLM（5）
- 未分类（1）

## AI/LLM

### [owner/repo](https://github.com/owner/repo)

> TypeScript · ⭐ 128 · 标签：`llm` `agent`

仓库简介……

**摘要**：README 中文摘要……
```

- `groupBy=none` 时只有「全部项目」一节；
- 未分类仓库归入「未分类」并固定排在最后；
- 标题 / 简介中的 Markdown 控制字符会转义，避免破坏文档结构；
- `includeSummary=0` 时不输出 `**摘要**` 行。

## 5. Obsidian Vault 格式

ZIP 目录（store 模式，标准解压工具可直接打开）：

```
README.md
10-项目/<分类>/<owner>--<repo>.md
20-分类/<分类>.md
```

- `groupBy=none` 时仓库笔记直接放在 `10-项目/` 下；
- `README.md`：统计 + 分类双链 + 最近更新（最多 20 条）；
- `20-分类/<分类>.md`：分类索引，列出该分类下的仓库双链；
- 仓库笔记使用 YAML frontmatter，标签自动转换为 Obsidian 标签：

```yaml
---
title: "owner/repo"
aliases:
  - "repo"
tags:
  - "openfactory"
  - "lang/typescript"
  - "tag/llm"
  - "cat/ai-llm"
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

正文包含简介、可选「## 摘要」、「## 标签」与「## 链接」。标签名会小写化、空格转 `-`，并去除 `# | [ ] , : { } ( ) " '` 等字符；分类与文件名保留中文，替换文件系统非法字符。

## 6. 边界与限制

- **数据量**：单用户千级仓库时 JSON / Markdown 体积可控；Obsidian ZIP 当前为 store（不压缩），体积接近原文，后续可替换为压缩实现；
- **文件名冲突**：`owner--repo` 已保证同名仓库唯一；极端情况下不同分类的同名文件仍可能覆盖，后续可加短哈希后缀；
- **摘要缺失**：无摘要仓库只输出简介，页面用 `withSummary` 提示覆盖率；
- **演示模式**：未配置 `VITE_API_BASE_URL` 时，前端使用内置演示数据在浏览器本地生成同构文件，便于无后端预览；
- **M9-04**：全量归档落地时复用本格式，并补充校验和、保留策略等备份元数据。

## 7. 相关代码

| 位置 | 内容 |
| --- | --- |
| `edge/src/export/build.ts` | 数据类型、参数归一化、三种格式构建、ZIP writer |
| `edge/src/routes/export.ts` | summary / export 路由与 D1 只读查询 |
| `edge/src/index.ts` | 挂载 `/api/export`，CORS 暴露 `Content-Disposition` |
| `admin/src/features/export/` | 导出页、API 封装、演示数据与前端 ZIP |
| `edge/scripts/export-helpers.test.mjs` | 纯函数与 ZIP 结构测试 |
