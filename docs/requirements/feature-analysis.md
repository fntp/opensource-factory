# 需求梳理 · Feature Analysis

> 需求编号：REQ-202610-0454 ｜ 阶段：立项 ｜ 维护人：fntp

本文档把立项阶段的 8 条要求逐条拆解为可验收的交付物，并记录落实位置。

## 1. 要求 → 落实映射

### #1 鉴权配置：只需要 GitHub 授权登录

- **解读**：登录体系仅实现 GitHub OAuth；Gitee / 邮箱密码 / 注册等一律不做。
- **落实**：
  - edge：`GET /api/auth/github/login|callback`、`GET /api/auth/me`、`POST /api/auth/logout`（会话存 D1，httpOnly Cookie）；
  - admin：登录页仅一个「使用 GitHub 登录」按钮 + 演示模式入口；移除模板中 Clerk / 注册 / 找回密码 / OTP 等全部内容；
  - **验收**：无任何其他登录入口残留（代码检索 `clerk` / `sign-up` 无业务引用）。

### #2 规范落实

| 子项 | 产出 |
| --- | --- |
| (a) 项目规范 | `docs/standards/project-spec.md` |
| (b) 代码约束规范 | `docs/standards/code-constraints.md` |
| (c) 需求规范 | `docs/standards/requirements-norms.md` |
| (d) 编码规范 | `docs/standards/coding-standards.md` |

### #3 文档落实

| 子项 | 产出 |
| --- | --- |
| (a) Agent 维护文档 | `docs/guides/agent-maintenance.md` + 根目录 `AGENTS.md` / `CLAUDE.md` |
| (b) 任务规划文档 | `docs/planning/roadmap.md` |
| (c) 计划文档 | `docs/planning/task-planning.md` |
| (d) 开发周期文档 | `docs/guides/dev-cycle.md` |

### #4 文档管理

- 根目录 `docs/` 统一存放：规范 / 指引 / 规划 / 需求 / 架构 / 集成 / 数据资产；
- 数据资产（D1 Schema）位于 `docs/assets/d1-schema.sql`，与 `edge/migrations/` 保持同步。

### #5 功能集成（已有功能直接融入）

参考项目的能力**移植**而非重写：

| 能力 | 来源 | 落位 |
| --- | --- | --- |
| GitHub 仓库拉取 / README 获取 | bookmark-recommender `github_service.py` | `vps/app/services/github_service.py` |
| 爬虫基建（httpx / bs4） | bookmark-recommender `scraper.py` | `vps/app/services/trending_crawler.py` |
| 向量化与语义检索 | bookmark-recommender `embedding.py` | `vps/app/services/embedding.py`（升级 BGE-M3 + 降级兜底） |
| 推荐编排 | bookmark-recommender `api/github.py` 的 `_run_recommendation` | `vps/app/services/recommender.py` |
| 管理端 UI 体系 | shadcn-admin | `admin/`（布局 / 组件 / 主题原样延续） |

### #6 参考项目

- **shadcn-admin**：admin 模板基线（保留其 UI 体系与交互）；
- **bookmark-recommender**：后端能力来源（FastAPI + 向量检索）；
- **github_trending**：⚠️ 仓库无法访问（404），见 [open-questions.md](./open-questions.md) Q1 与 [reference-projects.md](../integration/reference-projects.md)；当前以自研最小爬虫实现替代。

### #7 实施步骤

1. **梳理需求** → 本文档 + `spec.md`；
2. **项目基建** → monorepo（admin / edge / vps）+ CI + 环境模板；
3. **UI 风格延续模板** → admin 基于 shadcn-admin 改造（布局、组件、主题、配置抽屉全部保留）。

### #8 沟通机制（待确认问题）

- 原要求：不确定点向用户提供 choice 选项；
- 本任务为**自动执行**场景，改为：记录到 [open-questions.md](./open-questions.md)（问题 + 选项 + 默认处理），随交付上报。

## 2. 功能点清单（本迭代实现）

- [x] F1 登录页：GitHub 登录按钮 + 演示模式（无后端可预览）
- [x] F2 会话管理：`/api/auth/me` 拉取用户、退出登录
- [x] F3 仪表盘：资产统计卡 + Star 增长图 + 今日热榜
- [x] F4 我的仓库：列表 / 搜索 / 分类 / 标签 / Star 数
- [x] F5 分类与标签：分类清单 + 标签云
- [x] F6 每日热榜：榜单 / 语言 / 今日 Star
- [x] F7 智能推荐：匹配度 / 推荐理由 / 收藏 / 忽略
- [x] F8 任务调度：edge `POST /api/sync` → vps `/api/tasks/*`（Celery）
- [x] F9 数据层：D1 Schema（迁移文件）+ 本地 SQLAlchemy 模型

## 3. 范围外（明确不做 / 延后）

- Gitee OAuth 与 Gitee 热榜（延后，见 Q2）；
- 邮件 / Telegram 推送通道（M4）；
- 多用户与权限体系（当前为个人系统，单用户模型）。
