# 计划文档 — REQ-202610-0983 数据保留与隐私策略落地（M9-06）

> 文档编号：PL-202610-0983 ｜ 维护人：fntp ｜ 创建：2026-10-22
> 依赖：M5-08 安全审计（隐私边界复核）｜ 来源：`docs/requirements/backlog.md` · M9-06

## 1. 目标

把 M5-08 隐私边界清单里「保留期未定义、缺少数据主体导出 / 删除接口」的缺口补齐，形成可执行、
可验证、可审计的数据生命周期策略：

1. 定义各类个人数据的保留期、处理目的与清理动作（单一事实来源）；
2. 提供数据主体权利接口：个人数据导出（access / portability）与账号删除（erasure）；
3. 每日自动执行过期数据清理，保留清理审计记录；
4. 管理后台提供「隐私与数据」页面，展示策略、导出数据、删除账号；
5. VPS 本地镜像同步执行删除与保留清理，避免边缘删除后本地残留；
6. 文档、Schema、接口契约与安全审计清单同步更新。

## 2. 现状与差距

| 项 | 现状 | 差距 |
| --- | --- | --- |
| 会话 / 登录审计 / 安全事件 | 已有 30 / 30 / 90 天清理（M5-05） | 未统一编排、无审计留痕 |
| 热榜快照 | VPS 90 天归档清理（M2-08） | 公开数据，不涉及个人 |
| 用户 / 推荐 | 无保留期、无导出 / 删除接口 | M5-08 审计 medium 缺口 |
| 通知 / 更新提醒 / 建议 / 报告等 | 无清理 | 长期累积 |
| 隐私政策 | 仅安全审计文档内清单 | 无面向用户的策略与页面 |

## 3. 方案

### 3.1 保留策略（默认值，可配置）

| 数据类别 | 表 | 保留期 | 到期动作 |
| --- | --- | --- | --- |
| 账号资料 | `users` | 至用户主动删除 | 删除 |
| 会话 | `sessions` | 过期即删（最长 30 天） | 删除 |
| 登录审计 | `login_attempts` | 30 天 | 删除 |
| 安全事件 | `security_events` | 90 天 | 删除 |
| 限流计数 | `rate_limit_counters` | 窗口过期 | 删除 |
| 推荐记录 | `recommendations` | 未收藏 90 天 / 已收藏 365 天 | 删除 |
| 站内通知 | `notifications` | 已读 180 天 / 未读 365 天 | 删除 |
| 项目更新提醒 | `repo_updates` | 已读 180 天 / 未读 365 天 | 删除 |
| 推荐反馈 | `recommendation_feedback` | 365 天 | 删除 |
| 重复忽略 | `duplicate_dismissals` | 365 天 | 删除 |
| 标签 / 分类建议 | `tag_suggestions` / `category_suggestions` | 已处理 90 天 / 待处理 180 天 | 删除 |
| 精选报告 | `curated_reports` | 365 天 | 删除 |
| 扩展令牌 | `extension_tokens` | 撤销后 30 天 | 删除 |
| Telegram 绑定码 | `telegram_link_codes` | 过期即删 | 删除 |
| Telegram 绑定 | `telegram_links` | 至解绑 / 账号删除 | 删除 |
| 推送偏好 | `push_preferences` | 至账号删除 | 删除 |
| 运行指标 | `worker_metrics` | 90 天 | 删除 |
| 隐私审计 | `privacy_events` | 365 天 | 删除 |

策略版本：`2026-10-22`；代码单一事实来源 `edge/src/privacy/policy.ts`。

### 3.2 边缘 API（D1 主数据）

- `GET /api/privacy/policy`：公开策略（无需登录），返回版本、保留期、数据主体权利与出网点；
- `GET /api/privacy/export`：登录态，导出当前用户全部个人数据（JSON 附件，`no-store`）；
- `DELETE /api/privacy/account`：登录态，要求 `{"confirmation":"DELETE"}`，级联删除个人数据并清 Cookie；
- `POST /api/internal/privacy/cleanup`：内部令牌，手动触发保留清理（返回各表删除数）；
- Worker Cron 每日 03:20 UTC 自动执行清理。

### 3.3 VPS 本地镜像

- `POST /api/privacy/purge-user`（内部令牌）：删除本地 `recommendations` / 评估运行 /
  推送事件 / 投递记录 / `users` 行；
- `cleanup_privacy_data` Celery 任务（每日 04:27）清理本地过期推荐、推送事件、投递记录与评估运行；
- 新增 `PRIVACY_*` 配置项并在 `.env.example` 说明。

### 3.4 管理后台

- 新增 `/settings/privacy`「隐私与数据」页：
  - 保留策略表（类别 / 目的 / 保留期 / 说明）；
  - 导出个人数据（JSON 下载）；
  - 删除账号（输入 `DELETE` 二次确认，成功后回到登录页）；
  - 展示策略版本与数据主体权利说明。

### 3.5 审计与文档

- 新增 `privacy_events` 表：记录导出 / 删除 / 清理事件（只存用户 id 的 SHA-256，不存明文）；
- 更新 `docs/guides/privacy-retention.md`（策略与操作手册）、`security-audit.md` 隐私边界表、
  `data-model.md`、`architecture/overview.md` 接口边界、`docs/README.md`、backlog / roadmap / task-planning；
- 同步 `docs/assets/d1-schema.sql` 与迁移 `0023_privacy_lifecycle.sql`。

## 4. 任务拆分

| # | 任务 | 产出 | 状态 |
| --- | --- | --- | --- |
| 1 | 计划与策略设计 | 本文件 + 策略表 | ✅ |
| 2 | D1 迁移与 Schema | `0023_privacy_lifecycle.sql`、`d1-schema.sql` | ✅ |
| 3 | 边缘隐私模块 | policy / export / cleanup / routes / cron | ✅ |
| 4 | 边缘测试 | `privacy-policy.test.mjs` 等 | ✅ |
| 5 | VPS 删除与保留清理 | service / API / Celery / config / tests | ✅ |
| 6 | 管理后台页面 | `features/privacy/*`、路由、侧栏 | ✅ |
| 7 | 管理后台测试 | `privacy.test.ts` | ✅ |
| 8 | 文档同步 | guides / architecture / requirements / planning | ✅ |
| 9 | 全量检查 | edge typecheck + test、admin lint/build/test、vps pytest | ✅ |

## 5. 验收口径

- 未登录访问导出 / 删除返回 401；删除确认串错误返回 400；
- 导出内容覆盖用户资料、收藏、推荐、通知、更新提醒、偏好、建议、报告、令牌元数据、Telegram 绑定、
  会话元数据与隐私事件，且不含任何令牌明文 / 哈希；
- 删除账号后，上述表按 `user_id` 无残留，`users` 行不存在，Cookie 失效；
- 清理任务按保留期删除且返回各表计数，写入 `privacy_events`；
- 安全审计 `privacy-lifecycle` 缺口消失；
- 三端测试全绿。
