# 实施计划 · REQ-202610-0972 Telegram Bot 查询入口（收藏 / 推荐 / 热榜）

> 需求：REQ-202610-0972（backlog M8-03）｜ 分支：`feat/req-202610-0972-telegram-bot`
> 依赖：M4-04 Telegram 推送通道（已落地，`vps/app/services/telegram.py`）
> 基线：`b81c05c`（M7 验收集成分支）
> 目标：让用户不打开 Web 控制台，直接在 Telegram 里查询自己的收藏、当日推荐与热榜。

## 1. 现状与缺口

- M4-04 已实现 Telegram **推送**：VPS 每日把 `pushed` 推荐生成摘要，通过 Bot API `sendMessage` 下发，并记录 `telegram_deliveries`；
- 但 Bot 只是单向广播：用户无法主动问「我收藏了哪些支付项目」「今天有什么推荐」「热榜第一是什么」；
- Telegram 更新只能由公网 HTTPS 入口接收，VPS 是内网 / 家庭节点，不适合直接暴露 webhook；
- 用户与 `chat_id` 没有绑定关系，无法把 Telegram 会话映射到 D1 里的 `users.id`；
- 群组 chat_id 多人共用，若允许群组查询会暴露绑定用户的个人数据，因此本期只支持私聊。

## 2. 方案总览

```
Telegram Bot（与 M4-04 同一个 Bot，可选）
  → POST https://<edge>/api/telegram/webhook
     → 校验 X-Telegram-Bot-Api-Secret-Token（wrangler secret）
     → 解析命令 / 参数
     → chat_id → telegram_links.user_id
     → 按命令查询 D1（全部带 user_id）
        /favorites [关键词]  my_repositories + categories
        /recommend           recommendations（排除 dismissed / saved / expired）
        /trending [语言]     trending_snapshots 最新日期 → trending_repositories 回退
     → 生成中文 HTML 消息（纯函数、确定性）
     → 调 Bot API sendMessage 回复

admin 设置 → 通知设置 → Telegram 查询 Bot
  → GET  /api/telegram/status       查看配置 / 绑定状态
  → POST /api/telegram/link-code    生成 6 位绑定码（10 分钟有效）
  → DELETE /api/telegram/link       解绑当前用户
```

设计原则：

1. **边缘接收、D1 只读**：webhook 与查询都放在 edge Worker，不经过 VPS，不新增计算依赖；
2. **按用户隔离**：`telegram_links.chat_id` 唯一映射 `user_id`，所有查询 SQL 都带 `user_id = ?`；
3. **确定性文案**：命令解析、HTML 转义、消息拼装全部在 `edge/src/telegram/bot.ts`，不依赖网络与 LLM，node:test 可直接覆盖；
4. **安全默认**：未配置 `TELEGRAM_WEBHOOK_SECRET` / `TELEGRAM_BOT_TOKEN` 时 webhook 返回 503，不提供匿名入口；绑定码只存 sha-256 摘要；
5. **优雅降级**：热榜无快照时回退 `trending_repositories`；未绑定 / 无数据时返回明确中文提示，不抛错。

## 3. 数据模型

新增 D1 迁移 `0021_telegram_bot.sql`：

`telegram_links`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `chat_id` | TEXT PK | Telegram chat id（私聊 / 群组） |
| `user_id` | TEXT NOT NULL | 对应 `users.id`，唯一索引保证一人一聊 |
| `username` | TEXT | Telegram `@username`（可空） |
| `linked_at` | TEXT NOT NULL | 绑定时间（ISO） |
| `last_seen_at` | TEXT | 最近一次命令时间 |

`telegram_link_codes`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `code_hash` | TEXT PK | 绑定码的 sha-256 摘要（不存明文） |
| `user_id` | TEXT NOT NULL | 生成绑定码的用户 |
| `expires_at` | TEXT NOT NULL | 过期时间（ISO，10 分钟） |
| `created_at` | TEXT NOT NULL | 创建时间 |

索引：`telegram_links(user_id)` 唯一；`telegram_link_codes(user_id)`。

## 4. 接口契约

### 4.1 登录态接口（admin）

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/telegram/status` | GET | 配置 / 绑定状态、脱敏 chat id、命令清单 |
| `/api/telegram/link-code` | POST | 生成 6 位绑定码（10 分钟），返回 `code` / `expiresAt` / `deepLink` |
| `/api/telegram/link` | DELETE | 解绑当前用户的 Telegram 会话 |

### 4.2 Bot webhook（Telegram → edge）

`POST /api/telegram/webhook`，必须携带 `X-Telegram-Bot-Api-Secret-Token`；不参与 IP 限流（Telegram 出口 IP 共享，改由 secret 鉴权）。

支持命令：

| 命令 | 别名 | 说明 |
| --- | --- | --- |
| `/favorites [关键词]` | `/fav`、`/收藏` | 收藏列表，按 Star 降序，最多 5 条 |
| `/recommend` | `/rec`、`/推荐` | 待处理推荐，按精排分 / 匹配度排序 |
| `/trending [语言]` | `/hot`、`/热榜` | 最新热榜快照，按当日 Star 增量排序 |
| `/link <绑定码>` | `/bind`、`/绑定` | 绑定当前 Telegram 会话 |
| `/unlink` | `/解绑` | 解绑当前会话 |
| `/help` | `/start`、`/帮助` | 帮助与绑定指引 |

消息使用 `parse_mode=HTML`，动态内容全部转义；超过 3800 字符按行分片。

## 5. 配置

edge `wrangler.toml` / secrets：

| 变量 | 位置 | 说明 |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | secret | BotFather Token；与 M4-04 可复用同一个 Bot |
| `TELEGRAM_WEBHOOK_SECRET` | secret | `setWebhook` 时传入的 `secret_token`，用于校验 webhook |
| `TELEGRAM_BOT_USERNAME` | var | 可选，用于生成 `t.me/<bot>?start=<code>` 深链 |
| `TELEGRAM_API_BASE` | var | 默认 `https://api.telegram.org`，可指向自建反代 |

## 6. 交付物

| 文件 | 说明 |
| --- | --- |
| `edge/migrations/0021_telegram_bot.sql` | `telegram_links` / `telegram_link_codes` |
| `edge/src/telegram/bot.ts` | 命令解析、HTML 转义、消息拼装、分片（纯函数） |
| `edge/src/routes/telegram.ts` | webhook、状态、绑定码、解绑路由与 D1 查询 |
| `edge/src/index.ts` | 挂载 `/api/telegram` |
| `edge/src/types.ts` | Env 与 Telegram 行类型 |
| `edge/src/security/rate-limit.ts` | webhook 不参与 IP 限流 |
| `edge/scripts/telegram-bot.test.mjs` | 纯函数 + 路由 / 鉴权 / 用户隔离 / 绑定用例 |
| `admin/src/features/settings/notifications/telegram-bot-api.ts` | 状态 / 绑定码 / 解绑 API 与演示兜底 |
| `admin/src/features/settings/notifications/telegram-bot-panel.tsx` | 通知设置页「Telegram 查询 Bot」卡片 |
| `admin/src/features/settings/notifications/telegram-bot.test.ts` | 状态归一化 / 绑定码格式化用例 |
| 文档 | 本计划、架构总览、数据模型、D1 schema、backlog、roadmap、task-planning、open-questions、README |

## 7. 测试与验收

| 层 | 用例 |
| --- | --- |
| edge 纯函数 | 命令别名 / `@bot` 后缀 / 参数、HTML 转义、Star 与分数格式化、空数据、分片 |
| edge 路由 | webhook 未配置 503 / 错误 secret 401、非文本更新忽略、未绑定提示、绑定码过期 / 错误、`/favorites` 用户隔离与关键词、`/recommend` 排序、`/trending` 快照与回退、`/unlink` |
| admin 单元 | 状态归一化、chat id 脱敏、绑定命令与过期时间格式化 |
| 回归 | edge `npm run typecheck` + `npm test`；admin `npm run lint` + `npm run build` + `npm run test`；vps `pytest -q`（未改 VPS，回归确认） |

验收标准：

1. 在 admin 通知设置生成绑定码，Telegram 发送 `/link <code>` 后提示绑定成功；
2. `/favorites` 只返回当前绑定用户的收藏，支持关键词过滤；
3. `/recommend` 返回待处理推荐，`/trending` 返回最新热榜快照；
4. 未绑定会话发送查询命令得到绑定指引，不泄漏任何用户数据；
5. webhook 未配置或 secret 错误时拒绝请求；
6. 三端检查全绿，文档同步更新。

## 8. 风险与后续

- **Bot Token 双端使用**：M4-04 的 VPS 推送与本期 edge webhook 共用同一个 Bot Token 时，需在 VPS 与 edge 各配置一份；两边只做发送 / 接收，不冲突；
- **webhook 公网暴露**：必须配置 `TELEGRAM_WEBHOOK_SECRET`，并在 `setWebhook` 时传同一值；否则接口返回 503；
- **多用户 / 群组**：当前只允许私聊，群组 / 频道统一返回「请私聊使用」提示，避免多人共用 chat id 时暴露绑定用户数据（已记入 open-questions Q35）；
- **消息长度**：单次最多 5 条，正文按行分片；后续可加「更多」翻页与 Inline Keyboard；
- **数据时效**：收藏与推荐直接读 D1，热榜依赖最近一次抓取 / 快照任务；无数据时给出明确提示。
