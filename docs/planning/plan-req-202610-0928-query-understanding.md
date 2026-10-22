# 实施计划 · REQ-202610-0928 查询理解增强（同义词 / 技术栈词表）

> 需求：REQ-202610-0928（backlog M3-10）｜ 分支：`feat/req-202610-0928-query-understanding`
> 依赖：M3-04 语义搜索接口与页面（REQ-202610-0922）
> 目标：在不引入 LLM、不增加外部依赖的前提下，把用户的自然语言查询归一化为
> 「原查询 + 规范技术栈词 + 同义词扩展」，提升语义检索与关键词降级链路的召回。

## 1. 现状与缺口

- M3-04 已提供 `/api/search/{embed,query,semantic,status}`，查询文本直接交给
  `EmbeddingService` 编码，未做任何归一化或扩展；
- 用户常用「k8s」「postgres」「管理后台」「脚手架」等口语 / 别名，而仓库文本里
  多写作 `Kubernetes`、`PostgreSQL`、`admin`、`boilerplate`，直接编码会损失召回；
- edge 的 D1 关键词降级只使用原始 query 做单条 `LIKE`，同义词场景几乎必然 0 命中；
- 词表散落在 `readme.py` 的 `TECH_KEYWORDS`（仅用于技术栈提取），没有
  「别名 → 规范词」映射，也没有供检索复用的统一入口。

## 2. 方案总览

```
查询文本
  → normalize（空白折叠、大小写归一）
  → 词表匹配（技术栈词表 + 同义词表；ASCII 词边界 / 中文子串，长词优先）
  → QueryUnderstanding { query, rewritten, techStack, concepts, terms, keywordTerms }
      ├─ rewritten     → EmbeddingService 编码（语义检索 / Vectorize 查询向量）
      └─ keywordTerms  → edge D1 关键词降级（多词 OR LIKE）
```

设计原则：

1. **纯规则、确定性、零网络**：不调用 LLM，词表内置，测试可完全离线；
2. **原查询优先**：`rewritten` 始终以原查询开头，扩展词去重后追加，避免淹没原意；
3. **可关闭、可限量**：`SEARCH_QUERY_EXPANSION_ENABLED` 可整体关闭，
   `SEARCH_QUERY_EXPANSION_MAX_TERMS` 限制单次扩展词数量（默认 12）；
4. **未命中即原样返回**：无词表命中时 `rewritten == query`，行为与 M3-04 完全一致；
5. **词表可维护**：技术栈与同义词分开登记，新增词条只需改一个模块。

## 3. 词表设计

### 3.1 技术栈词表（`TECH_VOCAB`）

每条包含规范名、别名、关联词：

| 规范名 | 别名示例 | 关联扩展 |
| --- | --- | --- |
| Kubernetes | k8s、kube、k8s 集群 | container orchestration |
| PostgreSQL | postgres、pg、pgsql | relational database |
| JavaScript | js、es6、ecmascript | — |
| TypeScript | ts、typescript | — |
| Go | golang、go 语言 | — |
| React | reactjs、react.js | frontend |
| Vue | vuejs、vue.js、vue3 | frontend |
| NestJS | nest.js、nest | Node.js backend |
| Docker | container、容器 | containerization |
| PyTorch | torch | deep learning |
| …… | 覆盖语言 / 框架 / 数据库 / 中间件 / AI / 部署工具 | — |

> ASCII 别名使用「前后非字母数字」边界匹配，避免 `Go` 命中 `Google`、`Java` 命中
> `JavaScript`；中文别名按子串匹配；同一位置长别名优先（`react native` 优先于 `react`）。

### 3.2 同义词表（`CONCEPT_SYNONYMS`）

面向产品描述的概念组，例如：

| 概念 | 别名示例 | 扩展词 |
| --- | --- | --- |
| 管理后台 | 后台、后台管理、admin panel | admin、dashboard、management console |
| 脚手架 | 模板、样板、starter | boilerplate、template、starter kit |
| 组件库 | UI 库、组件集合 | component library、UI kit |
| 任务调度 | 定时任务、调度器 | scheduler、cron、task queue |
| 多租户 | 多租户 SaaS、tenant | multi-tenant、SaaS |
| 实时协作 | 协同编辑、多人协作 | realtime collaboration、CRDT |
| 可视化 | 图表、看板 | visualization、charts、dashboard |
| 爬虫 | 抓取、采集 | crawler、scraping |
| 机器学习 | ML、深度学习 | machine learning、deep learning |
| 大模型 | LLM、大语言模型 | LLM、large language model |
| …… | 覆盖常见业务 / 形态描述 | — |

## 4. 接口契约

### 4.1 VPS 新增 `POST /api/search/understand`

请求：`{ "query": "k8s 部署工具" }`

响应：

```json
{
  "query": "k8s 部署工具",
  "rewritten": "k8s 部署工具 Kubernetes container orchestration deployment",
  "expanded": true,
  "techStack": ["Kubernetes"],
  "concepts": ["部署"],
  "terms": ["Kubernetes", "container orchestration", "deployment"],
  "keywordTerms": ["k8s 部署工具", "Kubernetes", "container orchestration", "deployment"],
  "maxTerms": 12
}
```

### 4.2 既有接口扩展（向后兼容）

| 端点 | 变更 |
| --- | --- |
| `POST /api/search/embed` | 请求增加可选 `expand`（默认 `true`）；响应增加 `understanding`，`vector` 改为对 `rewritten` 编码 |
| `POST /api/search/query` | 请求增加可选 `expand`；响应增加 `understanding` |
| `POST /api/search/semantic` | 同上，`understanding` 随完整结果返回 |
| `GET /api/search/status` | 增加 `vocabulary`（技术栈 / 同义词条目数） |

### 4.3 edge `/api/search/semantic`

- 响应增加可选 `understanding`（来自 VPS embed / query 响应）；
- D1 关键词降级改为多词 OR LIKE：原查询 + `keywordTerms`，最多 8 个词；
- VPS 不可达时无 `understanding`，仍用原查询，行为与现状一致。

### 4.4 admin 搜索页

- 结果区展示「查询理解」标签：命中的技术栈（outline）与概念（secondary）；
- 未扩展时不展示，不改变现有布局与交互。

## 5. 文件清单

- `vps/app/services/query_understanding.py`（新增）：词表、匹配、`QueryUnderstanding`；
- `vps/app/services/semantic_search.py`：`search_local` / `search_semantic` 接入扩展；
- `vps/app/api/search.py`：新增 `/understand`，其余端点透传 `expand` 与 `understanding`；
- `vps/app/schemas.py`：`SearchQuery.expand`、`SearchUnderstandingOut` 与响应字段；
- `vps/app/config.py`、`vps/app/runtime.py`：新增 2 个配置键；
- `vps/.env.example`、`deploy/env/openfactory.env.example`：同步配置；
- `vps/tests/test_query_understanding.py`（新增）+ `test_semantic_search.py` 补充；
- `edge/src/routes/search.ts`、`edge/src/types.ts`：understanding 透传与多词关键词降级；
- `admin/src/features/search/{api.ts,index.tsx,utils.ts,search.test.ts}`：查询理解标签；
- 文档：`docs/architecture/overview.md`、`docs/requirements/backlog.md`、
  `docs/planning/{roadmap,task-planning}.md`、`docs/README.md`、`vps/README.md`、`edge/README.md`。

## 6. 验证计划

- `cd vps && .venv/bin/pytest -q`：新增词表匹配 / 扩展 / 去重 / 边界 / API 用例；
- `cd edge && npm run typecheck`：确认新增类型与路由改动 0 error；
- `cd admin && npm run lint && npm run build && npm run test`：回归 + 查询理解标签纯函数用例；
- `python -m compileall vps/app`、`git diff --check`。

## 7. 风险与边界

- 词表为人工维护，覆盖范围有限；新增领域词需同步补词表与用例；
- 扩展词可能引入噪声：默认限量 12 个、原查询始终保留，且可通过 `expand=false` 关闭；
- hash 兜底向量只反映字符 trigram，扩展收益有限；生产 BGE-M3 下收益更明显；
- 本需求不包含多轮问答（M6-09）、Rerank（M7-07）与 LLM 查询改写。
