# 数据保留与隐私策略（M9-06 / REQ-202610-0983）

> 本文是数据主体权利与保留期的落地说明。策略的唯一代码事实来源是
> `edge/src/privacy/policy.ts`；VPS 本地镜像的清理规则在
> `vps/app/services/privacy_retention.py`。

## 1. 目标与边界

- **数据主体权利**：访问 / 导出、删除、更正、限制处理；
- **自动保留**：边缘 D1 与 VPS 本地镜像都按保留期每日清理，避免无限累积；
- **最小化**：登录审计只存 IP 哈希，安全事件只存身份哈希，令牌只存 SHA-256；
- **可审计**：导出、删除、保留清理都写入 `privacy_events`，只记录事件类型、用户 id 哈希与聚合计数。

不采集密码、支付信息、通讯录或精确位置；GitHub 邮箱仅用于账号展示。

## 2. 边缘 API

| 方法与路径 | 鉴权 | 说明 |
| --- | --- | --- |
| `GET /api/privacy/policy` | 公开 | 返回策略版本、保留期、数据主体权利与第三方出网点 |
| `GET /api/privacy/export` | 会话 Cookie | 导出当前用户全部个人数据（JSON 附件，`Cache-Control: no-store`） |
| `DELETE /api/privacy/account` | 会话 Cookie | 删除账号；请求体必须为 `{"confirmation":"DELETE"}` |
| `POST /api/internal/privacy/cleanup` | `X-Internal-Token` | 手动触发一轮 D1 保留清理 |

导出不包含会话 token 哈希、扩展令牌哈希或任何密钥；删除在同一个 D1 batch 内
按 `user_id` 清理 15 张用户关联表、写入 `privacy_events` 审计并删除 `users` 行，
随后 best-effort 调用 VPS `POST /api/privacy/purge-user` 清理本地镜像。

## 3. 默认保留期

| 数据 | 位置 | 默认保留期 | 到期动作 |
| --- | --- | --- | --- |
| 账号资料 | D1 `users` | 保留至账号删除 | 删除账号时清除 |
| 登录会话 | D1 `sessions` | 过期即清理（最长 30 天） | 删除 |
| 登录审计 | D1 `login_attempts` | 30 天 | 删除 |
| 安全事件 | D1 `security_events` | 90 天 | 删除 |
| 推荐记录 | D1 / VPS `recommendations` | 未收藏 90 天 / 已收藏 365 天 | 删除 |
| 站内通知 | D1 `notifications` | 已读 180 天 / 未读 365 天 | 删除 |
| 项目更新提醒 | D1 `repo_updates` | 已读 180 天 / 未读 365 天 | 删除 |
| 推荐反馈 | D1 `recommendation_feedback` | 365 天 | 删除 |
| 重复项目忽略记录 | D1 `duplicate_dismissals` | 365 天 | 删除 |
| 标签 / 分类建议 | D1 `tag_suggestions` / `category_suggestions` | 待处理 180 天 / 已处理 90 天 | 删除 |
| 精选报告 | D1 `curated_reports` | 365 天 | 删除 |
| 扩展令牌 | D1 `extension_tokens` | 有效期内保留；撤销后 30 天 | 删除 |
| Telegram 绑定 | D1 `telegram_links` / `telegram_link_codes` | 保留至解绑 / 账号删除；绑定码 10 分钟 | 删除 |
| 推送偏好 | D1 `push_preferences` | 保留至账号删除 | 删除 |
| 运行指标 | D1 `worker_metrics` | 90 天 | 删除 |
| 隐私审计 | D1 `privacy_events` | 365 天 | 删除 |
| VPS 评估运行 | `recommendation_evaluation_runs` | 180 天 | 删除 |
| VPS 推送事件 | `push_events` | 180 天 | 删除 |
| VPS 推送送达记录 | `push_deliveries` / `email_deliveries` / `telegram_deliveries` / `push_receipts` | 365 天 | 删除 |
| VPS 隐私审计 | `privacy_events` | 365 天 | 删除 |

所有天数均可通过 `PRIVACY_*` 环境变量调整，上限 3650 天。调整后策略版本
（`PRIVACY_POLICY_VERSION`）应在发版时递增，便于审计对齐。

## 4. 定时任务

- **边缘**：Worker Cron `20 3 * * *`（UTC，每日 11:20 Asia/Shanghai）调用
  `cleanupExpiredData()`，单次 `db.batch()` 提交，失败只记日志不阻塞其他 Cron；
- **VPS**：Celery beat `cleanup-privacy-data-daily` 每日 `04:33`
  （Asia/Shanghai，`PRIVACY_CLEANUP_HOUR/MINUTE`）执行 `cleanup_privacy_data`；
- 两者都可手动触发：边缘 `POST /api/internal/privacy/cleanup`，VPS
  `POST /api/privacy/cleanup`（支持 `{"dryRun":true}`）。

## 5. VPS 内部接口

| 方法与路径 | 说明 |
| --- | --- |
| `POST /api/privacy/purge-user` | 按 `userId` 删除推荐、评估、推送事件 / 送达记录与 `users` 行；幂等 |
| `GET /api/privacy/retention` | 返回保留配置、待清理计数与策略版本 |
| `POST /api/privacy/cleanup` | 立即执行清理；`dryRun=true` 只统计不删除 |

均要求 `X-Internal-Token`（未配置 `INTERNAL_TOKEN` 时本地开发不启用）。
`my_repositories` 等全局仓库镜像没有 `user_id`，属于工作区共享数据，不随账号删除。

## 6. 管理后台

`/settings/privacy`（设置 → Privacy & Data）提供：

- 策略版本、数据主体权利与第三方处理清单；
- 完整保留期表格（类别 / 存储位置 / 保留期 / 到期动作）；
- 「下载我的数据」按钮（JSON 附件）；
- 危险区：输入 `DELETE` 后二次确认删除账号，成功后清除会话并返回首页。

## 7. 验证与运维

```bash
# 边缘
cd edge && npm run typecheck && npm test

# VPS
cd vps && .venv/bin/pytest -q tests/test_privacy_retention.py

# admin
cd admin && npm run lint && npm run build && npm run test
```

运维排查：

1. 查看策略：`curl https://<edge>/api/privacy/policy`；
2. 查看 VPS 待清理量：`curl -H "X-Internal-Token: ***" https://<vps>/api/privacy/retention`；
3. 手动 dry-run：`POST /api/privacy/cleanup {"dryRun":true}`，确认计数后再实际执行；
4. 审计：D1 `privacy_events` / VPS `privacy_events` 按 `event_type`、`created_at` 查询。

## 8. 已知限制

- 备份中的历史副本不参与在线删除，按备份保留策略自然过期；
- 删除账号后，VPS 清理为 best-effort（5 秒超时），失败会在边缘日志记录，
  可通过 `purge-user` 内部接口重试（幂等）；
- 策略版本目前为常量，修改保留期后需随发版更新版本号。
