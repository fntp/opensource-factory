# 开源项目工厂 · OpenFactory

> 个人开源资产管理与智能推荐系统 —— 一站式收录、分类、发现与推荐优质开源项目。

[![CI](https://github.com/fntp/opensource-factory/actions/workflows/ci.yml/badge.svg)](https://github.com/fntp/opensource-factory/actions/workflows/ci.yml)

## ✨ 项目简介

日常浏览 GitHub / Gitee 时收藏的开源项目往往散落各处，难以按业务线复用，也难以发现真正适合自己的新项目。**开源项目工厂** 希望解决三个问题：

1. **资产散落** —— 一键同步 Starred / 个人仓库，多维标签 + 树状分类统一管理；
2. **发现困难** —— 每日抓取全网热榜，自动清洗 README 并生成中文摘要；
3. **推荐缺失** —— 基于向量语义匹配，把「你的技术栈」与「全网新项目」连接起来，每日定向推送。

## 🏗 架构总览

```
┌───────────────────────────── Cloudflare 边缘（0 成本） ─────────────────────────────┐
│                                                                                     │
│   admin/  前端控制台 (React 19 + Vite + TanStack Router + shadcn/ui)                 │
│      │                                                                              │
│   edge/   API 调度层 (Workers + Hono + TypeScript)                                   │
│      ├── D1        关系型元数据（仓库 / 热榜 / 分类 / 用户）                            │
│      └── Vectorize 向量特征存储（语义检索）                                            │
│                                                                                     │
└──────────────────────────────────────┬──────────────────────────────────────────────┘
                                       │ 内部 API（X-Internal-Token）
┌──────────────────────────────────────▼──────────────────────────────────────────────┐
│                        本地 VPS 算力节点（私有化，隐私安全）                            │
│   vps/   FastAPI + Celery                                                           │
│      ├── 定时爬虫    GitHub Trending / Gitee 热榜                                     │
│      ├── 文本清洗    README 去噪、技术栈提取                                          │
│      ├── 本地推理    Ollama (DeepSeek) 摘要 · BGE-M3 向量化                           │
│      └── 推荐引擎    语义匹配 + 每日 Push（通知中心 / Bark / Telegram / Email）         │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## 📁 目录结构

```
opensource-factory/
├── admin/     # 前端控制台（基于 shadcn-admin 模板定制）
├── edge/      # Cloudflare Workers API（Hono + D1 + Vectorize）
├── vps/       # 本地算力节点（FastAPI + Celery + Ollama/BGE-M3）
├── docs/      # 全部项目文档与数据资产（规范 / 规划 / 需求 / 架构）
└── .github/   # CI 工作流
```

## 🚀 快速开始

### 前端控制台（admin）

```bash
cd admin
npm install
cp .env.example .env      # 未配置后端时自动进入「演示模式」
npm run dev               # http://localhost:5173
```

常用命令：`npm run lint` / `npm run build` / `npm run test`。

### 边缘 API（edge）

```bash
cd edge
npm install
npm run dev               # wrangler dev，本地 D1
npm run db:migrate:local  # 应用 D1 迁移
```

### 本地算力节点（vps）

```bash
cd vps
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # 轻量依赖；完整推理见 requirements-ml.txt
uvicorn app.main:app --reload            # http://localhost:8000
celery -A app.tasks.celery_app worker -l info   # 任务队列
```

## 📚 文档

所有项目文档集中在 [`docs/`](./docs/README.md)：

| 分类 | 说明 |
| --- | --- |
| [规范 standards](./docs/standards/project-spec.md) | 项目 / 代码约束 / 需求 / 编码规范 |
| [指引 guides](./docs/guides/agent-maintenance.md) | Agent 维护文档、开发周期、部署 / 升级 / 回滚 / 故障处理 [运维手册](./docs/guides/operations-runbook.md) |
| [规划 planning](./docs/planning/roadmap.md) | 任务规划、计划文档 |
| [需求 requirements](./docs/requirements/spec.md) | 需求规格、功能梳理、待确认问题 |
| [架构 architecture](./docs/architecture/overview.md) | 架构总览、数据模型 |
| [集成 integration](./docs/integration/reference-projects.md) | 参考项目集成说明 |

## 🤝 参与贡献

请阅读 [CONTRIBUTING.md](./CONTRIBUTING.md) 与 [AGENTS.md](./AGENTS.md)（AI Agent 维护指南）。

## 📄 许可证

[MIT](./LICENSE)。`admin/` 目录基于 [shadcn-admin](https://github.com/satnaing/shadcn-admin)（MIT © Sat Naing）定制，保留其原始 [LICENSE](./admin/LICENSE) 声明。
