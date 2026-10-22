# 实施计划 · REQ-202610-0961 自动分类建议（按业务线）

> 需求：REQ-202610-0961（backlog M7-02）｜ 分支：`feat/req-202610-0961-auto-classification`
> 依赖：M1-09 分类树 CRUD（REQ-202610-0901）、M7-01 自动打标建议（REQ-202610-0960）
> 基线：`feat/req-202610-0959-m6-acceptance` @ `400ca31`
> 目标：根据仓库名称、简介、语言、摘要与标签，自动推断所属**业务线**并给出分类建议；
> 用户在控制台逐条确认后写入 `my_repositories.category_id`，降低人工归类成本。

## 1. 现状与缺口

- `categories` / `my_repositories.category_id` 已建模，但当前集成线上没有可用的分类写入闭环；
  M1-09 的分类树 CRUD 分支（`feat/req-202610-0901-category-tree`）尚未并入 M6 集成线，本需求先合入该依赖；
- M2-04 已产出中文摘要（`readme_summary`），M6-04 技术栈图谱已有语言 / 框架词表，但没有任何
  「仓库 → 业务线 → 分类」的推导能力；
- M7-01 自动打标建议与本需求共享「摘要 → 结构化建议 → 人工确认 → 落库」闭环，本需求复用同一交互范式，
  但不强依赖 M7-01 的分支（其尚未合入集成线），标签仅作为可选加权信号；
- 用户面对大量收藏仓库时逐条选择分类成本高，且不同时间口径不一致。

## 2. 方案总览

```
admin /category-suggestions
  ├─ GET  /api/category-suggestions            列表（按用户隔离，pending / accepted / dismissed）
  ├─ POST /api/category-suggestions/generate   对当前用户有简介 / 摘要的仓库批量生成建议
  ├─ POST /api/category-suggestions/accept     采纳（确保分类存在 → 写 my_repositories.category_id）
  └─ POST /api/category-suggestions/dismiss    忽略
        ↓
edge（登录态）
  ├─ 从 D1 取当前用户仓库（名称 / 简介 / 语言 / 摘要 / 标签）
  ├─ 调 VPS POST /api/category-suggestions/generate（X-Internal-Token，内联仓库快照）
  │     └─ 业务线词表：AI / 金融支付 / 电商零售 / 企业服务 / 开发工具 / 数据工程 / DevOps …
  ├─ VPS 不可用或未覆盖的仓库 → edge 本地规则兜底
  └─ 建议 upsert 到 D1 category_suggestions（user_id + repo_id + category_name 唯一）
```

设计原则：

1. **按业务线而非按语言**：语言只作为弱信号；主信号是仓库名称、简介、摘要中的业务关键词；
2. **可解释**：每条建议带 `score`、`reason`、`evidence`（命中字段与片段），不输出黑盒结果；
3. **建议与执行分离**：生成只写 `category_suggestions`，不直接改仓库分类；采纳后才写 `category_id`；
4. **账号隔离**：edge 所有 SQL 带 `user_id = ?`，采纳时再次校验仓库归属；
5. **优雅降级**：VPS 不可达时 edge 用本地业务线词表生成，页面不空白；
6. **幂等**：同一用户 + 仓库 + 分类只保留一条建议；重复生成更新分数与理由，不覆盖已采纳 / 已忽略状态；
7. **不新增外部依赖**：规则词表纯本地，测试不访问网络。

## 3. 业务线词表（首批）

| key | 分类名 | 典型关键词（节选） |
| --- | --- | --- |
| `ai` | AI / 大模型 | LLM、GPT、Transformer、RAG、embedding、大模型、机器学习、推理、微调、Agent |
| `fintech` | 金融 / 支付 | payment、fintech、wallet、ledger、支付、金融、对账、结算、风控、信贷 |
| `ecommerce` | 电商 / 零售 | ecommerce、cart、checkout、order、inventory、电商、商城、购物车、订单、库存 |
| `saas` | 企业服务 / SaaS | SaaS、CRM、ERP、tenant、workflow、多租户、客户关系、审批、工单、管理后台 |
| `devtools` | 开发工具 | CLI、SDK、compiler、linter、scaffold、开发工具、编译器、脚手架、命令行、插件 |
| `data-infra` | 数据工程 | database、SQL、Kafka、ETL、warehouse、数据库、缓存、消息队列、数据管道、数据仓库 |
| `cloud-devops` | DevOps / 云原生 | Kubernetes、Docker、CI/CD、Terraform、serverless、容器、编排、部署、运维、监控 |
| `security` | 安全 / 合规 | security、OAuth、JWT、encryption、vulnerability、安全、认证、授权、加密、漏洞、合规 |
| `web-frontend` | 前端开发 | React、Vue、Svelte、Next.js、Tailwind、CSS、前端、组件库、设计系统 |
| `mobile` | 移动端 | iOS、Android、Flutter、React Native、Swift、移动端、安卓、小程序、跨平台 |
| `content-media` | 内容 / 媒体 | CMS、blog、markdown、wiki、video、audio、内容、博客、文档、知识库、视频、音频 |
| `education` | 教育 / 学习 | education、course、tutorial、quiz、教育、学习、教程、课程、题库、培训 |
| `productivity` | 效率 / 办公 | productivity、todo、calendar、email、automation、效率、待办、日历、邮件、办公、自动化 |
| `gaming` | 游戏 / 娱乐 | game、Unity、Unreal、Godot、游戏、娱乐、引擎、玩家 |
| `iot` | 物联网 / 嵌入式 | IoT、embedded、firmware、Arduino、ESP32、MQTT、物联网、嵌入式、固件、传感器 |
| `blockchain` | 区块链 / Web3 | blockchain、Web3、Ethereum、Solidity、NFT、DeFi、区块链、智能合约、以太坊 |
| `healthcare` | 医疗 / 健康 | healthcare、medical、hospital、patient、医疗、健康、医院、患者、诊断 |
| `backend-api` | 后端与 API | API、gateway、microservice、REST、GraphQL、后端、网关、微服务、服务端 |

> 词表命中规则：名称权重 3、标签权重 2、简介权重 2、摘要权重 1.5、语言匹配 0.5；
> 同一仓库最多输出 `perRepo`（默认 3，1~5）条，低于 `minScore`（默认 0.55）丢弃。

## 4. 接口契约

### 4.1 VPS `POST /api/category-suggestions/generate`（X-Internal-Token）

请求：

```json
{
  "repos": [
    {
      "repoId": "owner/repo",
      "name": "repo",
      "description": "项目简介",
      "language": "TypeScript",
      "summary": "中文摘要",
      "tags": ["支付", "Node.js"]
    }
  ],
  "perRepo": 3,
  "minScore": 0.55
}
```

响应：

```json
{
  "generatedAt": "2026-10-22T12:00:00.000Z",
  "scanned": 1,
  "suggested": 2,
  "items": [
    {
      "repoId": "owner/repo",
      "suggestions": [
        {
          "categoryName": "金融 / 支付",
          "businessLine": "fintech",
          "score": 0.82,
          "reason": "名称命中「payment」；摘要命中「支付」",
          "evidence": "……支持多渠道支付与对账……"
        }
      ]
    }
  ]
}
```

### 4.2 edge

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/category-suggestions` | GET | 登录态；`status=pending\|accepted\|dismissed\|all`、`repoId`、`limit`、`offset`；返回列表 + 汇总 + 分类 |
| `/api/category-suggestions/generate` | POST | 登录态；`{repoIds?, limit?, perRepo?, minScore?}`；生成并 upsert，返回 `source`（vps/local/mixed）与统计 |
| `/api/category-suggestions/accept` | POST | 登录态；`{ids?}` 或 `{repoId, categoryName?}`；确保分类存在 → 写 `category_id` → 标记 accepted |
| `/api/category-suggestions/dismiss` | POST | 登录态；`{ids, reason?}`；标记 dismissed，重复生成不再打扰 |

列表项 DTO：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 稳定 id（用户 + 仓库 + 分类哈希） |
| `repoId` / `repoName` / `repoUrl` | string | 仓库标识与地址 |
| `summary` | string | 摘要（用于人工判断） |
| `categoryName` | string | 建议分类名 |
| `businessLine` | string | 业务线 key |
| `score` | number | 置信度 0~1 |
| `reason` / `evidence` | string | 命中理由与证据片段 |
| `status` | `pending\|accepted\|dismissed` | 状态 |
| `currentCategory` | string \| null | 仓库当前分类名 |

### 4.3 D1 表 `category_suggestions`（迁移 `0014`）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | TEXT | 主键（稳定哈希） |
| `user_id` | TEXT | 用户 id |
| `repo_id` | TEXT | 仓库 `owner/repo` |
| `category_name` | TEXT | 建议分类展示名 |
| `business_line` | TEXT | 业务线 key |
| `score` | REAL | 置信度 |
| `reason` / `evidence` | TEXT | 理由 / 证据 |
| `status` | TEXT | pending / accepted / dismissed |
| `created_at` / `updated_at` | TEXT | 时间 |

唯一索引 `(user_id, repo_id, category_name)`；列表索引 `(user_id, status, updated_at DESC)`。

## 5. 交付物

| 文件 | 说明 |
| --- | --- |
| `vps/app/services/category_suggestions.py` | 业务线词表、归一化、命中打分、证据抽取（纯函数） |
| `vps/app/api/category_suggestions.py` | 内部生成接口 |
| `vps/app/schemas.py` | 请求 / 响应模型 |
| `vps/app/main.py` | 挂载路由 |
| `vps/tests/test_category_suggestions.py` | 词表 / 打分 / 排序 / 限制 / 接口契约 |
| `edge/src/category-suggestions/rules.ts` | 本地业务线词表与规则打分（VPS 降级） |
| `edge/src/category-suggestions/helpers.ts` | 归一化、稳定 id、合并、状态归一化 |
| `edge/src/routes/category-suggestions.ts` | 列表 / 生成 / 采纳 / 忽略路由 |
| `edge/migrations/0017_category_suggestions.sql` | D1 建议表 |
| `edge/scripts/category-suggestions.test.mjs` | 纯函数与路由契约测试 |
| `admin/src/features/category-suggestions/api.ts` | DTO、请求封装、演示数据 |
| `admin/src/features/category-suggestions/utils.ts` | 分组、汇总、格式化、排序 |
| `admin/src/features/category-suggestions/index.tsx` | 建议页：汇总卡、生成、业务线分组、采纳 / 忽略 |
| `admin/src/features/category-suggestions/category-suggestions.test.ts` | 工具函数测试 |
| `admin/src/routes/_authenticated/category-suggestions/index.tsx` | 文件式路由 |
| `admin/src/components/layout/data/sidebar-data.ts` | 「开源资产」新增「分类建议」 |
| 文档 | 本计划、架构总览、数据模型、D1 Schema、backlog / roadmap / task-planning、三端 README |

## 6. 测试与验收

| 层 | 用例 |
| --- | --- |
| vps | 业务线关键词命中 / 名称优先 / 标签加权 / 语言弱信号 / 多业务线排序 / perRepo / minScore / 无文本跳过 / 接口鉴权与响应 |
| edge | 归一化 / 稳定 id / 合并去重 / 状态归一化 / 本地兜底 / DTO 映射 / 路由鉴权与 upsert |
| admin | 分数格式化 / 按业务线分组 / 汇总统计 / 演示数据 |
| 回归 | `vps .venv/bin/pytest -q`；`edge npm run typecheck && npm test`；`admin npm run lint && npm run build && npm run test` |

验收标准：

1. 登录用户访问 `/category-suggestions` 能看到待确认建议、覆盖仓库数、平均置信度与已采纳数；
2. 点击「生成建议」后，有简介 / 摘要的仓库出现 1~N 条业务线分类建议，每条带理由与证据；
3. 采纳后分类写入 `categories`（不存在时自动创建）与 `my_repositories.category_id`，仓库列表 / 分类页可见；
4. 忽略后该建议不再出现在待确认列表，重复生成不覆盖忽略状态；
5. VPS 不可用时页面仍可通过本地规则生成建议；
6. 三端检查全绿，文档同步更新。

## 7. 风险与后续

- **业务线口径**：首批 18 条业务线覆盖常见个人开源资产，长尾项目可能落到「后端与 API」或无法命中；
  后续可接 LLM 分类或让用户自定义业务线；
- **摘要质量**：摘要缺失时仅靠名称 / 简介，置信度会下降；列表展示摘要与证据供人工判断；
- **同义分类**：用户可能已有「支付系统」等自定义分类，采纳时按名称精确匹配，匹配不到会新建；
  后续可做分类别名 / 合并（M1-10 标签合并的同类问题）；
- **规模**：单次生成默认 200 个仓库、每仓库 3 条，规则匹配为 O(仓库数 × 词表)，个人库规模可接受；
- **M7-01 协同**：标签建议上线后可将标签作为更强信号传入，本期已预留 `tags` 字段。
