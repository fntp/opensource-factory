# 需求规格说明书 · OpenFactory

> 需求编号：REQ-202610-0454 ｜ 项目：开源项目工厂（OpenFactory） ｜ 负责人：fntp

## 1. 系统概述

个人开源资产管理与智能推荐系统，解决「开源项目散落、难以按业务线复用、无法定向推荐」的痛点。采用 **轻量级边缘控制台（Cloudflare 0 成本） + 本地私有化算力节点（深度学习 / 隐私安全）** 的混合架构。

### 1.1 架构分工

- **Cloudflare 边缘平台**：前端控制台、轻量 API 调度、关系型元数据（D1）、向量特征存储（Vectorize）；
- **本地 VPS 算力节点**：Python 异步任务、全网热榜爬虫、本地深度学习 / Embedding 推理（Ollama / BGE-M3），通过 API 与 Cloudflare 同步。

## 2. 核心功能需求

### 2.1 模块一：开源资产同步与多维管理（边缘 Web 端）

1. **多平台账号授权**：集成 GitHub / Gitee OAuth，一键导入 Starred Repos 与个人/组织仓库。
   > 立项阶段收窄：**本期仅要求 GitHub 授权登录**（其余暂不处理）。
2. **增量同步机制**：定时与手动触发，按 Commit / Star 变更增量写入 D1。
3. **多维标签与树状分类**：
   - 业务线分类树（如 `[电商业务线] -> [支付组件]`）；
   - 自定义 Tag 系统（如 `#Nextjs`、`#开箱即用`、`#DDD架构`）。
4. **快速秒级检索**：SQL 全匹配与组合筛选，「即选即用」，避免重复造轮子。

### 2.2 模块二：全网热榜抓取与数据探索（VPS 侧）

1. **多源定时爬虫**：每日 Cron 抓取 GitHub Trending、Gitee Index 等热榜；
2. **文本清洗与摘要**：自动提取 README.md，过滤噪点，提取核心功能、技术栈与适用场景。

> Q2 确认（2026-10-22，REQ-202610-0917 / M2-09）：本期仅启用 GitHub Trending；Gitee 探索页抓取不接入，仅保留 `platform='gitee'` 字段与预留入口，后续迭代再评估（见 `open-questions.md` Q2）。

### 2.3 模块三：深度学习与定向推荐引擎（VPS + Vectorize）

1. **项目向量化**：本地模型（如 `bge-m3`）对 README 摘要生成向量，同步存入 Cloudflare Vectorize；
2. **业务需求语义匹配（RAG）**：自然语言检索（如「寻找支持多租户的 NestJS 管理后台模板」），打通「已收藏库」与「每日热榜」；
3. **定向 Push**：每日评估符合用户技术栈的高质量项目，推送至通知中心或 Bark / Telegram / Email。

## 3. 技术栈选型

| 架构层级 | 部署目标 | 技术选型 |
| --- | --- | --- |
| 前端 / UI | Cloudflare Pages | React + shadcn/ui（模板风格延续 shadcn-admin） |
| 后端 API / 边缘 | Cloudflare Workers | Hono.js / TypeScript（原生支持 D1 / Vectorize） |
| 关系型数据库 | Cloudflare D1 | Serverless SQLite |
| 向量数据库 | Cloudflare Vectorize | 边缘向量检索 |
| 爬虫与 AI 节点 | 本地 VPS | Python（FastAPI + Celery + PyTorch） |
| Embedding / LLM | 本地 VPS | Ollama（DeepSeek）/ BGE-M3 |

## 4. 数据库设计

核心三表（需求原文，见 `docs/assets/d1-schema.sql`）：

- `my_repositories`：已收藏 / 自有仓库（含 `readme_summary`、`category_id`）；
- `trending_repositories`：热榜项目（含 `stars_today`、`tech_stack`、`crawled_at`）；
- `categories`：分类（`parent_id` 支持无限级）。

本仓库在保持以上字段不变的前提下扩展了用户、会话、标签、推荐等表，详见 [data-model.md](../architecture/data-model.md)。

## 5. 立项阶段要求（REQ-202610-0454 原文落实）

| # | 要求 | 落实 |
| --- | --- | --- |
| 1 | 鉴权配置：仅 GitHub 授权登录 | edge `/api/auth/github/*` + admin 登录页（含演示模式兜底） |
| 2 | 规范落实（项目/代码约束/需求/编码） | `docs/standards/` 四份规范 |
| 3 | 文档落实（维护/规划/计划/周期） | `docs/guides/`、`docs/planning/` |
| 4 | 文档管理：根目录 docs 存放全部文档与数据资产 | `docs/` 全量落位 |
| 5 | 功能集成：参考项目已有功能直接融入 | vps / edge / admin 三端移植（见 integration 文档） |
| 6 | 参考项目：shadcn-admin + github_trending + bookmark-recommender | 见 [reference-projects.md](../integration/reference-projects.md) |
| 7 | 实施步骤：梳理需求 → 项目基建 → UI 延续模板 | 本迭代已完成（见 planning） |
| 8 | 沟通机制：不确定点给 choice 询问 | 自动任务场景改为 `open-questions.md` 记录（含选项与默认值） |

## 6. 非功能要求

- **成本**：边缘侧尽量控制在 Cloudflare 免费额度内；
- **隐私**：LLM / Embedding 默认本地推理，数据不出服务器；
- **可用性**：外部依赖（LLM / 模型 / 目标站点）失效时系统降级可用；
- **性能**：检索接口 P95 < 300ms（D1 索引）；推荐生成离线完成。
