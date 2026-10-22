# 实施计划 · REQ-202610-0932 Bark 通道（M4-03）

> 需求：REQ-202610-0932（backlog M4-03）｜ 分支：`feat/req-202610-0932-bark-channel`
> 依赖：M4-02 站内通知中心（REQ-202610-0931，独立分支并行开发）
> 目标：在 VPS 侧新增 Bark 推送通道，把每日进入 `pushed` 状态的推荐推送到 iOS Bark，支持配置自检、手动测试、定时投递与失败重试，且不影响推荐主流程。

## 1. 背景与现状

- M4-01 每日评估任务（REQ-202610-0930）已把推荐分为 `qualified` / `filtered`，09:00 的 `daily_push` 只把 `qualified` 标记为 `pushed`；
- M4-02 站内通知中心从 D1 的 `pushed` 推荐物化为站内通知，解决「打开控制台能看到」；
- Bark 是 iOS 上的轻量推送 App，提供 `POST {server}/push` 的 HTTP API（device key + 标题 + 正文 + 跳转链接），适合作为站内通知之外的实时提醒通道；
- 当前 VPS 没有任何外部推送通道，也没有投递状态，无法回答「今天推了几条、哪条失败、失败原因」；
- 推送偏好（M4-06）、去重与静默（M4-07）、完整回执（M4-08）不在本需求范围，本需求只做 Bark 通道本身与最小可用的幂等 / 可观测能力。

## 2. 方案总览

```
09:00 daily_push：qualified → pushed（M4-01）
09:05 send_bark_notifications（本需求）
  → 读取本地 recommendations：status=pushed 且 bark_sent_at IS NULL
  → 关联 trending_repositories / my_repositories 补全描述、语言、Star、链接
  → 生成中文 Bark 消息（标题 owner/name；正文简介 + 推荐理由 + 匹配度元信息）
  → POST {BARK_SERVER_URL}/push（device_key / group / level / sound / icon / url）
  → 成功：bark_sent_at=now、清空 bark_error；失败：bark_error=原因，保留待下次重试
```

设计取舍：

- **发送端放在 VPS**：Bark device key 属于服务端密钥，不能进浏览器；VPS 已有 Celery beat 与完整的推荐 / 仓库数据，避免 edge 为每条推送回查 D1；
- **与 M4-02 的关系**：站内通知中心负责「应用内可见」，Bark 负责「应用外提醒」，两者消费同一批 `pushed` 推荐，互不阻塞；M4-02 未合并时本通道也可独立工作；
- **最小幂等**：用 `recommendations.bark_sent_at` 标记已投递，避免定时任务重跑导致重复推送；`bark_error` 保留最近一次失败原因，成功即清空；
- **失败不阻塞**：Bark 未配置 / 网络失败 / 返回非 200 一律结构化返回，不抛异常影响 Celery 主流程；
- **可测试**：HTTP 调用统一走 `httpx`，测试用 `MockTransport`，不访问网络。

## 3. 配置（VPS）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `BARK_ENABLED` | `false` | 通道总开关；关闭时任务直接 skipped |
| `BARK_SERVER_URL` | `https://api.day.app` | Bark 服务地址，支持自建（自动拼接 `/push`） |
| `BARK_DEVICE_KEY` | 空 | Bark device key（密钥，仅存 `.env`，接口不回显） |
| `BARK_GROUP` | `OpenFactory` | 通知分组 |
| `BARK_SOUND` | 空 | 提示音（如 `minuet.caf`），空则用 Bark 默认 |
| `BARK_ICON` | 空 | 通知图标 URL |
| `BARK_LEVEL` | `active` | `active` / `timeSensitive` / `passive` / `critical` |
| `BARK_TIMEOUT_SECONDS` | `10` | 单次请求超时 |
| `BARK_MAX_PER_RUN` | `5` | 单次任务最多投递条数，避免一次刷屏 |
| `BARK_DRY_RUN` | `false` | 试运行：只生成消息不发送、不写投递标记 |

## 4. 数据模型

`recommendations` 增加两列（VPS 本地 SQLite，`init_db` 幂等补列）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `bark_sent_at` | DATETIME | Bark 成功投递时间；NULL 表示未投递 |
| `bark_error` | TEXT | 最近一次投递失败原因（截断 300 字符），成功后清空 |

不新增投递表：完整的多通道投递记录与回执由 M4-08 统一设计，本需求只保留最小状态，避免与后续需求重复建模。

## 5. 接口

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/push/bark/status` | GET | 通道状态：是否启用 / 已配置、待投递 / 已投递 / 失败计数、最近失败原因（不返回 device key） |
| `/api/push/bark/test` | POST | 同步发送一条测试通知；未启用或未配置返回 400 |
| `/api/push/bark/dispatch` | POST | 入队投递任务（`user_id` / `limit` 可选），返回 `202 {taskId}` |

内部鉴权沿用 `require_internal_token`（`X-Internal-Token`）。

## 6. 任务与调度

- 新增 Celery 任务 `app.tasks.jobs.send_bark_notifications`（薄封装，调用 `dispatch_bark_notifications`）；
- beat：每日 09:05 执行（在 09:00 推送准备之后）；
- 支持手动 `POST /api/push/bark/dispatch` 或 `send_bark_notifications.delay(...)` 重跑；
- 任务返回 `{status, candidates, sent, failed, skipped, dryRun, errors}`，便于日志与运维排查。

## 7. 文件清单

- `vps/app/services/bark.py`（新增）：Bark 客户端、消息构建、投递编排、状态统计
- `vps/app/api/push.py`（新增）：Bark 状态 / 测试 / 入队接口
- `vps/app/schemas.py`：Bark 状态、测试请求 / 响应模型
- `vps/app/config.py`、`vps/app/runtime.py`：10 个 `BARK_*` 配置与自检键
- `vps/app/models.py`、`vps/app/db.py`：推荐表投递标记列与幂等补列
- `vps/app/tasks/jobs.py`、`vps/app/tasks/celery_app.py`：任务与 09:05 beat
- `vps/app/main.py`：挂载 `/api/push` 路由
- `vps/.env.example`、`deploy/env/openfactory.env.example`：配置模板
- `vps/tests/test_bark.py`（新增）：消息构建、客户端成功 / 失败、投递幂等 / 重试 / 限额 / dry-run、状态与接口
- `vps/README.md`：Bark 通道使用与排障
- `docs/architecture/overview.md`、`docs/architecture/data-model.md`：推送数据流与字段
- `docs/requirements/backlog.md`、`docs/planning/task-planning.md`：M4-03 交付登记
- 本计划文档

## 8. 验证计划

- `cd vps && .venv/bin/pytest -q`：全量回归 + 新增 Bark 用例；
- `python -m compileall vps/app`、`git diff --check`；
- `vps/tests/test_deploy_assets.py`：确认 `REQUIRED_ENV_KEYS` 与 `Settings` 字段一致、两份 env 模板覆盖全部键；
- 不访问网络：Bark HTTP 全部使用 `httpx.MockTransport`；
- 本需求不改 edge / admin，无需重复跑前端构建（合并前仍按项目要求跑 edge typecheck 确认契约未变）。

## 9. 风险与边界

1. **Bark 服务不可达 / device key 失效**：任务记录 `bark_error` 并保留待投递状态，下次 09:05 或手动 dispatch 重试；不会阻塞推荐生成 / 评估 / 站内通知；
2. **单用户口径**：当前 VPS 是单用户镜像，`BARK_DEVICE_KEY` 为全局配置；多用户 device key 与通道开关由 M4-06 推送偏好承接；
3. **刷屏风险**：`BARK_MAX_PER_RUN` 默认 5，配合 M4-07 去重 / 静默策略进一步收敛；本需求不实现静默时段；
4. **重复推送**：以 `bark_sent_at` 做最小幂等；进程在「发送成功、落库前」崩溃的极端场景可能重复一次，可接受，M4-08 引入 delivery id 后可彻底消除；
5. **M4-02 依赖**：站内通知中心分支独立开发，本需求不修改 edge / D1；合并后两者消费同一批 `pushed` 推荐，语义一致。
