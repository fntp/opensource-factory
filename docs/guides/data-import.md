# 数据导入（外部收藏迁移）

> 需求：REQ-202610-0980（M9-03，P2，依赖 M1-05）｜入口：admin `/import` ｜ API：`/api/import/*`

把其他收藏工具（浏览器书签、表格、脚本导出）中的仓库迁移到 OpenFactory。
导入分两步：**先预览、再执行**。预览只解析与比对，不写库；执行时服务端会重新解析同一份内容，
避免客户端伪造统计。冲突（仓库已被其他用户收藏）会自动跳过，不会修改他人数据。

## 1. 支持的格式

| 格式 | 识别方式 | 适用场景 |
| --- | --- | --- |
| JSON | 内容以 `{` / `[` 开头 | `openfactory.knowledge.v1` 回读、脚本导出、`{ items }` 或对象数组 |
| CSV | 首行含可识别表头 | 表格软件导出的收藏清单，支持逗号 / 制表符 / 分号 |
| 书签 HTML | 含 `NETSCAPE-Bookmark-file` 或 `<a href>` | Chrome / Edge / Firefox 导出的书签文件 |

页面默认「自动识别」，也可以手动指定格式。内容上限 **2 MB**，单次最多 **2000 个仓库**；
超出部分会截断并在预览中提示。

### 1.1 JSON

推荐直接使用知识库导出的 `openfactory.knowledge.v1`（见 [knowledge-export.md](./knowledge-export.md)），
可直接回读：

```json
{
  "schema": "openfactory.knowledge.v1",
  "version": 1,
  "repositories": [
    {
      "fullName": "ollama/ollama",
      "url": "https://github.com/ollama/ollama",
      "description": "本地运行大语言模型",
      "summary": "在本地运行大模型",
      "language": "Go",
      "stars": 120000,
      "forks": 9000,
      "category": "AI/LLM",
      "tags": ["本地模型", "推理"]
    }
  ]
}
```

同时兼容：

- `{ "items": [...] }`；
- 顶层对象数组 `[ {...}, {...} ]`；
- 单条对象（含 `url` / `fullName` / `full_name` 之一）。

字段别名：`fullName` / `full_name` / `repo` / `repository` / `id` 都可表示 `owner/repo`；
`url` / `html_url` / `link` 表示仓库链接；`desc` 等价 `description`；`readmeSummary` 等价 `summary`。

### 1.2 CSV

首行必须是表头，列顺序任意。支持逗号、制表符（TSV）与分号分隔；字段可用双引号包裹，
引号内允许逗号和换行，`""` 表示转义的双引号。示例：

```csv
full_name,html_url,description,language,stars,tags,category
ollama/ollama,https://github.com/ollama/ollama,"本地运行大语言模型",Go,120000,"本地模型, 推理",AI/LLM
shadcn-ui/ui,https://github.com/shadcn-ui/ui,"可复制粘贴的 React 组件",TypeScript,80000,"React, 组件库",前端
```

可识别表头（大小写、空格、下划线、连字符不敏感）：

| 目标字段 | 表头别名 |
| --- | --- |
| 仓库 | `fullName` / `full_name` / `repo` / `repository` / `id` |
| 链接 | `url` / `html_url` / `link` |
| 描述 | `description` / `desc` |
| 摘要 | `summary` / `readmeSummary` |
| 语言 | `language` |
| Star / Fork | `stars` / `stargazersCount`、`forks` / `forksCount` |
| 分类 | `category` / `categoryName` |
| 标签 | `tags`（逗号 / 中文逗号 / 分号分隔） |
| 平台 | `platform`（`github` / `gitee`，缺省按链接推断） |

没有可识别表头时返回 `missing_header`，整批不导入。

### 1.3 浏览器书签 HTML

Chrome / Edge / Firefox 的「导出书签」文件可直接上传：

- 只导入指向 GitHub / Gitee 仓库的链接，其他书签（文章、文档、首页等）记为 `unsupported_url`；
- 默认开启「书签文件夹 → 分类」：取最近一层非默认文件夹名作为分类；
- `Bookmarks bar` / `Other bookmarks` / `书签栏` / `其他书签` / `收藏夹` 等默认根目录会被忽略；
- 书签标题作为仓库描述（若该条没有描述）；
- 可关闭文件夹映射，全部归入未分类。

## 2. 预览与执行

### 2.1 预览 `POST /api/import/preview`

请求体：

```json
{
  "content": "<文件原文>",
  "format": "auto",
  "useFolders": true,
  "createCategories": true
}
```

`format` 可为 `auto` / `json` / `csv` / `html`。响应：

```json
{
  "format": "json",
  "total": 128,
  "new": 96,
  "update": 24,
  "conflict": 6,
  "invalid": 2,
  "duplicates": 3,
  "truncated": false,
  "sample": [
    {
      "fullName": "ollama/ollama",
      "platform": "github",
      "url": "https://github.com/ollama/ollama",
      "description": "本地运行大语言模型",
      "language": "Go",
      "stars": 120000,
      "category": "AI/LLM",
      "tags": ["本地模型"],
      "status": "new"
    }
  ],
  "issues": [{ "row": 7, "reason": "invalid_repo", "value": "not-a-repo" }]
}
```

状态含义：

| 状态 | 含义 | 执行时的处理 |
| --- | --- | --- |
| `new` | 库中不存在 | 新增仓库 |
| `update` | 当前用户已收藏（或历史数据无归属） | 合并更新：空字段补齐、Star / Fork 取较大值、分类不覆盖已有值 |
| `conflict` | 已被其他用户收藏 | 跳过，不改动对方数据 |
| `invalid` | 无法解析 / 非仓库链接 | 跳过，计入 `issues` |

`duplicates` 表示同一文件内重复的条目数（大小写不敏感，标签合并）。样例最多返回 50 条，
`issues` 最多 100 条。

### 2.2 执行 `POST /api/import/execute`

请求体与预览一致。服务端重新解析并写库，响应：

```json
{
  "runId": "imp_m7x2k1_a1b2c3d4e5f6",
  "format": "json",
  "total": 128,
  "imported": 96,
  "updated": 24,
  "skipped": 8,
  "conflicts": 6,
  "invalid": 2,
  "duplicates": 3,
  "categoriesCreated": 4,
  "tagsCreated": 11,
  "tagsLinked": 132,
  "truncated": false
}
```

写入内容：

- `my_repositories`：按 `owner/repo` UPSERT；只更新本人或历史无归属记录，他人记录不覆盖；
- `categories`：`createCategories=true` 时按名称大小写不敏感查找或创建顶级分类；
- `tags` / `repo_tags`：标签不存在时创建，已存在则复用；每个仓库最多 20 个标签；
- `import_runs`：记录本次导入的来源格式与计数（不保存文件内容）。

### 2.3 历史 `GET /api/import/history?limit=10`

返回当前用户最近导入记录，`limit` 范围 1–50，默认 10。页面「最近导入」表格使用该接口。

## 3. 错误码

| HTTP | `error` | 说明 |
| --- | --- | --- |
| 400 | `invalid_json` | 请求体不是合法 JSON |
| 400 | `invalid_body` | 缺少 `content` 或字段类型错误 |
| 400 | `content_required` | 内容为空 |
| 400 | `unsupported_format` | `format` 不是 `auto/json/csv/html` |
| 401 | `unauthorized` | 未登录 |
| 413 | `content_too_large` | 内容超过 2 MB |
| 429 | `rate_limited` | 写接口限流（60 次/分钟） |

解析层面的问题不会返回 4xx，而是出现在预览的 `issues` 中，方便用户逐条修正。

## 4. 已知边界

- `my_repositories` 以 `owner/repo` 为全局主键，同一实例内一个仓库只能归属一个用户；
  因此导入时他人已收藏的仓库只能跳过（`conflict`），详见 `docs/requirements/open-questions.md` Q36；
- 导入不拉取 GitHub / Gitee 元数据，Star / 描述等以文件内容为准，后续可由同步任务刷新；
- 导入内容不落盘、不入审计表，`import_runs` 只保留计数；
- 演示模式（未配置 `VITE_API_BASE_URL`）下预览与执行均由前端模拟，不会调用后端。
