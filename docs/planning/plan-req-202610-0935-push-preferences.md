# 实施计划 · REQ-202610-0935 推送偏好设置（时间 / 阈值 / 通道开关）

> 需求：REQ-202610-0935（backlog M4-06）｜ 分支：`feat/req-202610-0935-push-preferences`
> 依赖：M4-02 站内通知中心（REQ-202610-0931）
> 目标：让每个用户自行设置每日推荐推送的时间、时区、匹配度 / 质量分阈值与通道开关，
> 并让 VPS 推送任务严格按偏好筛选，避免「一刀切 09:00 全量推送」。

## 1. 现状与缺口

- M4-01 评估任务已产出 `qualified` 推荐，M4-02 通知中心已能惰性物化 `pushed` 推荐；
- 但推送时间固定在 Celery beat 09:00，所有用户同一时刻、同一阈值；
- 没有用户级偏好存储：无法关闭推送、调整时间、提高门槛或选择 Bark / Telegram / Email；
- 通道任务（M4-03~05）即将接入，需要统一的通道开关来源。

## 2. 方案总览

```
admin「设置 → 推送偏好」
  → GET /api/push-preferences（edge，登录态，未保存返回默认值）
  → PUT /api/push-preferences（全量覆盖，D1 upsert）
       ↓ D1 push_preferences（唯一数据源）
VPS Celery beat 每 10 分钟
  → GET /api/internal/push-preferences（X-Internal-Token，批量拉取）
  → 对每个有待推送推荐（qualified）的用户：
       ├─ enabled=false → 跳过
       ├─ 无任何通道开启 → 跳过
       ├─ 当前本地时间不在 HH:MM + 10 分钟窗口 → 跳过（仅定时任务）
       └─ 按 min_score / min_quality_score 过滤 → 标记 pushed
  → edge 通知中心惰性物化站内通知；后续通道按 channels 下发
```

设计要点：

- **D1 为偏好唯一数据源**，VPS 不落偏好表；edge 不可达时回退默认值，不阻塞推送；
- **定时任务每 10 分钟轮询**，用用户本地时区判断是否到达推送窗口，支持跨午夜；
- **手动触发默认立即推送**（`respect_schedule=false`），便于调试与补推；
- 阈值只作用于 `qualified` 推荐：匹配度优先 `match_score`，缺失回退 `score`；
  质量分仅在 `>0`（已评估）时参与，避免历史数据被默认阈值误杀。

## 3. 数据模型

### 3.1 `push_preferences`（D1，迁移 `0011_push_preferences.sql`）

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `user_id` | TEXT PK | — | 用户 id |
| `enabled` | INTEGER | 1 | 总开关 |
| `time_of_day` | TEXT | `09:00` | 本地推送时间 HH:MM |
| `timezone` | TEXT | `Asia/Shanghai` | IANA 时区 |
| `min_score` | REAL | 0.35 | 匹配度阈值 0~1 |
| `min_quality_score` | REAL | 0.55 | 质量分阈值 0~1 |
| `channel_inapp` | INTEGER | 1 | 站内通知 |
| `channel_bark` | INTEGER | 0 | Bark |
| `channel_telegram` | INTEGER | 0 | Telegram |
| `channel_email` | INTEGER | 0 | Email |
| `updated_at` | TEXT | — | ISO 时间 |

未保存偏好的用户不强制落库，读取时返回默认值。

## 4. 接口

| 端点 | 方法 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| `/api/push-preferences` | GET | 登录态 | 当前用户偏好（`{ preferences, isDefault, availableChannels }`） |
| `/api/push-preferences` | PUT | 登录态 | 保存偏好（校验时间 / 时区 / 阈值 / 通道类型） |
| `/api/internal/push-preferences` | GET | `X-Internal-Token` | 全部偏好；`?userId=` 查单个 |

## 5. VPS 行为

- 新增 `app/services/push_preferences.py`：偏好模型、归一化、`is_due`、`matches_thresholds`、
  `PushPreferenceClient`（httpx，失败返回空字典）；
- `daily_push` 新增 `user_id` / `respect_schedule` / `now` 参数：
  - 未指定用户时按 `qualified` 推荐去重出目标用户；无用户级推荐时兼容全局推荐；
  - 逐用户应用开关、通道、时间窗口与阈值；
  - 返回 `pushed` / `skippedUsers` / `users`（含跳过原因）；
- Celery beat 从固定 09:00 改为每 10 分钟，`kwargs={"respect_schedule": True}`；
- 配置新增 `PUSH_DEFAULT_*`、`PUSH_TIME_WINDOW_MINUTES`、`PUSH_PREFERENCES_TIMEOUT_SECONDS`。

## 6. 前端

- `admin/src/features/settings/notifications/` 从静态模板改为真实设置页：
  - 总开关、时间（`input[type=time]`）、时区下拉、两个阈值数字输入；
  - 四个通道开关与说明；未开启任何通道时给出警示；
  - 保存 / 恢复默认、加载态、错误提示、当前摘要与「默认设置」标记；
- `api.ts` 提供类型、默认值、归一化 / 校验、`fetchPushPreferences` / `savePushPreferences`；
  演示模式（无 `VITE_API_BASE_URL`）下返回默认值并本地保存。

## 7. 测试与验收

| 层 | 用例 |
| --- | --- |
| edge | `scripts/push-preferences-route.test.mjs`：时间 / 阈值 / 时区校验、D1 行解析、通道标签、upsert 参数顺序 |
| vps | `tests/test_push_preferences.py`：归一化、默认值、时区换算、跨午夜窗口、阈值过滤、内部客户端降级、`daily_push` 集成 |
| admin | `push-preferences.test.ts`：默认值、响应解析、校验、摘要文案 |

验收标准：

1. 设置页可读取 / 保存偏好，刷新后保持；
2. 关闭推送或无通道的用户不再收到定时推送；
3. 未到推送时间的用户在定时任务中被跳过，手动触发不受时间限制；
4. 低于阈值的推荐保持 `qualified`，不会被标记 `pushed`；
5. 三端 lint / typecheck / build / test 全绿。

## 8. 风险与后续

- **时区依赖系统 tzdata**：容器需安装 tzdata，否则 `ZoneInfo` 回退 UTC（已做异常回退）；
- **每 10 分钟轮询**：偏好读取为一次批量 HTTP 请求，用户量大时需分页（当前上限 1000）；
- **通道下发**：本需求只负责开关与筛选，Bark / Telegram / Email 的实际发送由 M4-03~05 接入；
- **去重与静默**：M4-07 将在此基础上增加去重窗口与免打扰策略。
