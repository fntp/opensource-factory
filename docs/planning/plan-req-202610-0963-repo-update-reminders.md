# 实施计划 · REQ-202610-0963 收藏项目更新提醒（M7-04）

> 需求：收藏项目更新提醒（新版本 / 重大变更）  
> 依赖：M1-07 增量同步（按 `pushed_at` / star 变化避免全量）  
> 分支：`feat/req-202610-0963-repo-update-reminders`

## 1. 目标与范围

为已收藏仓库提供「新版本 / 重大变更」提醒：

- VPS 每日扫描收藏库的 GitHub Release（无 Release 时回退 Tag），与上次扫描的版本对比；
- 新版本写回 edge / D1，并按仓库归属分发给每个收藏用户；
- 版本号主版本跃迁（如 `v1.x` → `v2.0`）或 Release 文案命中 breaking change 关键词时标记为「重大变更」；
- admin 新增「更新提醒」页：未读 / 重大变更 / 新版本统计、筛选、标记已读、忽略、手动扫描；
- 同步写入站内通知中心（`type=repo_update`），复用 M4-02 通知能力。

不做：邮件 / Bark / Telegram 单独推送（沿用现有通知中心与推送偏好，不在本需求新增通道）；Gitee Release（当前收藏同步以 GitHub 为主，保留平台字段）。

## 2. 数据模型

D1 新增 `repo_updates`（迁移 `0015_repo_updates.sql`）：

| 字段 | 说明 |
| --- | --- |
| `id` | 稳定 ID（用户 + 仓库 + 版本哈希） |
| `user_id` / `repo_id` | 归属用户与仓库 |
| `repo_name` / `repo_url` | 冗余展示字段 |
| `type` | `release` / `major` |
| `version` | Release tag 或 Tag 名 |
| `title` / `summary` / `url` | Release 标题、摘要、链接 |
| `published_at` / `detected_at` | 上游发布时间 / 本次发现时间 |
| `status` | `unread` / `read` / `dismissed` |
| `read_at` / `payload` / `created_at` | 已读时间、扩展 JSON、入库时间 |

唯一索引 `(user_id, repo_id, version)` 保证重复扫描幂等；`(user_id, status, detected_at DESC)` 支撑列表与未读统计。

VPS 本地 `my_repositories` 增加 `latest_release_tag` / `latest_release_name` / `latest_release_url` / `latest_release_at` / `latest_release_checked_at`，作为增量扫描基线。

## 3. 流程

1. Celery beat 每日 06:37 执行 `scan_repo_updates`（也可由 admin「立即扫描」触发 edge → VPS 入队）。
2. VPS 读取收藏库仓库，逐个调用 GitHub `/repos/{owner}/{repo}/releases`（失败 / 空时回退 `/tags`），选出最新非草稿版本。
3. 与本地 `latest_release_tag` 对比：
   - 首次扫描：仅记录基线，不产生提醒（避免历史版本刷屏）；
   - 版本变化：生成事件，主版本跃迁或命中 breaking 关键词时 `type=major`，否则 `release`；
   - 版本未变：跳过。
4. VPS 通过 `POST {edge}/api/internal/repo-updates/ingest` 回写事件。
5. edge 按 `my_repositories.user_id` 扇出到每个收藏用户，写入 `repo_updates`，并写入 `notifications`（`dedupe_key=repo-update:{repoId}:{version}`）。
6. admin `/updates` 读取 `GET /api/repo-updates`，支持状态 / 类型筛选与已读、忽略、全部已读。

## 4. 接口

| 端 | 方法 | 路径 | 说明 |
| --- | --- | --- | --- |
| edge | GET | `/api/repo-updates` | 列表 + 汇总（status / type / limit / offset） |
| edge | GET | `/api/repo-updates/unread-count` | 未读数 |
| edge | POST | `/api/repo-updates/read-all` | 全部已读 |
| edge | POST | `/api/repo-updates/:id/read` | 单条已读 |
| edge | POST | `/api/repo-updates/:id/dismiss` | 忽略 |
| edge | POST | `/api/repo-updates/scan` | 触发 VPS 扫描当前用户仓库 |
| edge | POST | `/api/internal/repo-updates/ingest` | VPS 回写（`X-Internal-Token`） |
| VPS | POST | `/api/repos/updates/scan` | 入队扫描（内部令牌） |

## 5. 任务拆分

1. 文档与迁移：计划文档、D1 迁移、数据模型 / Schema 资产。
2. VPS：`repo_updates` 服务（版本解析 / 重大变更判定 / 增量扫描 / 回写）、GitHub releases 客户端、Celery 任务与调度、API、配置与模板。
3. edge：helpers、`repo_updates` 路由与内部回写、通知中心联动、类型与入口挂载。
4. admin：`repo-updates` feature（api / utils / 页面 / 测试）、文件式路由、侧边栏与未读徽标、通知类型文案。
5. 文档同步：架构总览、数据模型、D1 Schema、backlog / roadmap / task-planning、三端 README。
6. 验证：VPS pytest、edge typecheck + node:test、admin lint + build + Vitest；`git diff --check`。

## 6. 风险与降级

- GitHub 限流 / 404：单仓库失败不影响整批；无 Release 回退 Tag；无 Token 时任务跳过并返回结构化原因。
- 首次上线不提醒历史版本：以首次扫描作为基线，从下一次版本变化开始提醒。
- 多用户收藏同一仓库：edge 按 `my_repositories.user_id` 扇出；无归属用户时跳过。
- 通知中心与更新提醒双写：`repo_updates` 为事实表，`notifications` 仅做站内提醒，二者各自幂等。
