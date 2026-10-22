# 架构总览 · Architecture Overview

> 文档编号：AR-01 ｜ 维护人：fntp ｜ 变更架构时同步更新

## 1. 总体架构

```
                      ┌──────────────────────────────┐
                      │           用户浏览器          │
                      └──────────────┬───────────────┘
                                     │ HTTPS
                 ┌───────────────────▼───────────────────┐
                 │        Cloudflare Pages（admin/）      │
                 │  React 19 · Vite · TanStack Router     │
                 └───────────────────┬───────────────────┘
                                     │ /api/*（cookie 会话）
                 ┌───────────────────▼───────────────────┐
                 │      Cloudflare Workers（edge/）       │
                 │  Hono · TypeScript                     │
                 │  ├── 鉴权（GitHub OAuth · 会话）        │
                 │  ├── 元数据读写（D1）                   │
                 │  ├── 向量检索（Vectorize，M3）          │
                 │  └── 任务调度（→ VPS）                  │
                 └───────┬───────────────────┬───────────┘
                         │ D1 / Vectorize    │ 内部 API
                         │                   │ X-Internal-Token
                 ┌───────▼──────┐   ┌────────▼─────────────────────┐
                 │  Cloudflare  │   │      本地 VPS 算力节点        │
                 │  D1 + Vector │   │      （vps/）                 │
                 │              │   │  FastAPI · Celery · Redis     │
                 └──────────────┘   │  ├── 爬虫（GitHub Trending）  │
                                    │  ├── 清洗 / 摘要（Ollama）    │
                                    │  ├── 向量化（BGE-M3）         │
                                    │  └── 推荐 / 推送              │
                                    └──────────────────────────────┘
```

## 2. 组件职责

| 组件 | 目录 | 职责 | 不该做的事 |
| --- | --- | --- | --- |
| 前端控制台 | `admin/` | 展示、交互、调用 edge API | 不存密钥、不做业务计算 |
| 边缘 API | `edge/` | 鉴权、调度、D1 读写、Vectorize 检索 | 不跑长任务、不跑模型 |
| 算力节点 | `vps/` | 爬虫、清洗、摘要、向量化、推荐、推送 | 不对外暴露（仅内网/内部 token） |
| 数据资产 | `docs/assets/` | Schema、样例数据 | — |

## 3. 关键数据流

### 3.1 登录流（GitHub OAuth）

```
浏览器 → /api/auth/github/login → 302 GitHub authorize
GitHub → /api/auth/github/callback?code → edge 换取 token → 拉取用户 → upsert users → 建会话 → 302 回前端
前端 → /api/auth/me（cookie）→ 返回 AuthUser
```

### 3.2 同步流（资产）

```
admin「同步仓库」→ POST /api/sync（edge）→ POST {VPS}/api/tasks/sync（X-Internal-Token）
→ Celery 拉取 GitHub Starred/自有仓库 → upsert → 摘要（Ollama）→ 写回 D1 → 前端可见
```

### 3.3 热榜流

```
Celery beat 每日 → 抓取 GitHub Trending → 清洗解析 → upsert trending_repositories
→ 摘要/技术栈提取 → 向量化（M3-02）→ 同步 Vectorize（M3-03）
```

### 3.4 推荐流（RAG）

```
用户自然语言查询 → edge → Vectorize 检索（已收藏库 + 热榜库）
→ 结果聚合排序 → 返回（含匹配度与理由）；每日推送任务见 M4
```

每日推荐生成与评估（M3-05 + M4-01）：

```
Celery beat 08:30 → 收藏库平均向量（复用 repo_vectors）→ 热榜候选
→ 排除已收藏 → 相似度 × 0.8 + 热榜热度 × 0.2 → 阈值过滤 → top_k
→ upsert recommendations（status=new、match_score=原始相似度；旧 new 未入选标记 expired）
08:45 每日评估 → 质量分 = 仓库质量 × 0.7 + 理由质量 × 0.3
→ 双重门槛：match_score ≥ EVAL_MATCH_THRESHOLD 且 quality_score ≥ EVAL_QUALITY_THRESHOLD
→ qualified / filtered，写 recommendation_evaluation_runs
→ 09:00 推送准备只把 qualified 标记为 pushed
```

### 3.5 向量化流（M3-02）

```
同步 / 抓取完成 → 自动入队 vectorize_repositories（或 POST /api/tasks/vectorize）
→ 按批读取 my_repositories / trending_repositories
→ 文本哈希 + 模型 + 后端判断增量 → EmbeddingService（BGE-M3 / hash 降级）
→ upsert repo_vectors（逐批提交 + 游标）→ 运行状态可查询 / 可断点续跑
→ M3-03 批量同步 Cloudflare Vectorize
```

### 3.6 向量索引同步流（M3-03）

```
Celery beat（每 30 分钟）或 POST /api/vector-index/sync
→ VPS 读取本地 repo_vectors（仅 text_hash 变更 / 上次失败项；force 可全量）
→ 按批 POST {EDGE_BASE_URL}/api/internal/vectors/upsert（X-Internal-Token）
→ edge Worker 通过 Vectorize 绑定批量 upsert
→ VPS 写 vector_sync_state（逐条状态）/ vector_sync_runs（运行统计）

对账（kind=reconcile）：POST /api/internal/vectors/check 比对缺失 / 过期向量并修复；
可选 list + delete 清理孤儿（默认关闭）。
```

### 3.7 Email 推送流（M4-05）

```
Celery beat 09:10 或 POST /api/tasks/send-email-digest
→ 读取 recommendations.status='pushed'（默认回溯 24h，按质量分 / 匹配度排序）
→ 水合 trending_repositories（回退 my_repositories）→ 渲染中文摘要（plain + HTML）
→ 校验 EMAIL_* 配置 / 收件人 → smtplib 投递（STARTTLS / SSL / AUTH，瞬时错误重试）
→ 写 email_deliveries（sent / failed，收件人脱敏、Message-ID、错误脱敏）
→ 同日同收件人已有 sent 记录时跳过（force 可补发）
```

未启用 / 未配置 / 无数据 / SMTP 失败分别返回 `disabled` / `not_configured` / `empty` / `failed`，
不阻塞每日推送主流程；站内通知中心（M4-02）与本通道互不影响。

### 3.8 Bark 推送流（M4-03）

```
Celery beat（每天 09:05）或 POST /api/push/bark/dispatch
→ 读取 recommendations：status='pushed' 且 bark_sent_at IS NULL
  （可选 user_id 过滤，按 quality_score / score 降序取前 BARK_MAX_PER_RUN 条）
→ 组装中文消息（标题 owner/name；正文 = 简介 + 推荐理由 + 匹配度 / 语言 / Star）
→ POST {BARK_SERVER_URL}/push（device_key / title / body / group / level / url）
→ 成功：写 bark_sent_at、清空 bark_error；失败：写 bark_error（截断 300 字符）留待重试

降级：BARK_ENABLED=false 或 BARK_DEVICE_KEY 为空 → 任务 skipped；
BARK_DRY_RUN=true → 只返回预览，不发送、不写标记；
网络 / Bark 返回异常 → 单条失败不中断整批。
```

M4-02 站内通知中心与本通道消费同一批 `pushed` 推荐，彼此独立：站内通知失败不影响 Bark 投递，反之亦然。

### 3.9 Telegram 推送流（M4-04）

```
Celery beat 09:05（daily_push 之后）或 POST /api/tasks/send-telegram-digest
→ 读取最近 TELEGRAM_DIGEST_WINDOW_HOURS 小时内 status=pushed 的推荐
→ 关联 trending_repositories（标题 / 简介 / 链接 / 今日 Star）
→ 生成中文 HTML 摘要（转义 + 按 3800 字符分片，≤ Telegram 4096 上限）
→ POST {TELEGRAM_API_BASE}/bot{token}/sendMessage（429 / 5xx / 网络异常指数退避）
→ 写 telegram_deliveries（sent / failed / pending；同日同会话最小幂等）
```

未启用 / 未配置 / 无数据时任务返回结构化状态并直接跳过，不访问网络；Bot Token 仅存
VPS 本机 `.env`，状态接口只返回脱敏 chat id。

### 3.10 推送记录与回执（M4-08）

```
Bark / Telegram / Email 每次实际发送
→ push_records.create_delivery：写 push_deliveries（channel / kind / target / status）
→ 发送结束：finish_delivery 回写 sent / failed / skipped、消息数与 message_id
→ 服务商回调或人工补记：POST /api/push/receipts
→ push_receipts 追加 accepted / delivered / bounced / failed 流水
→ 回执更新 push_deliveries.receipt_status，并同步 email_deliveries / telegram_deliveries 状态
```

查询：`GET /api/push/records`（通道 / 状态 / 类型 / 时间 / 关键字 + 分页）、
`GET /api/push/records/stats`（分通道 / 分状态计数与送达率）、
`GET /api/push/records/{id}`（详情 + 回执时间线）。目标在 API 输出时统一脱敏；
已 `delivered` 的记录不会被迟到的 `accepted` / `bounced` 回执降级。

## 4. 接口边界

### 4.1 admin ↔ edge（JSON over HTTPS，Cookie 会话）

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/auth/github/login` | GET | 302 → GitHub 授权（`redirect` 参数回跳） |
| `/api/auth/github/callback` | GET | OAuth 回调（code → 会话） |
| `/api/auth/me` | GET | 当前用户（未登录 401） |
| `/api/auth/logout` | POST | 退出（204） |
| `/api/repos` | GET | 仓库列表（`?q=` / `?categoryId=`） |
| `/api/trending` | GET | 热榜（`?limit=`） |
| `/api/recommendations` | GET | 推荐列表 |
| `/api/categories` | GET | 分类 + 标签 |
| `/api/dashboard/stats` | GET | 仪表盘统计 |
| `/api/sync` | POST | 触发同步任务（202） |

### 4.2 edge ↔ vps（内部 API，`X-Internal-Token`）

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/tasks/sync` | POST | 入队仓库同步 |
| `/api/tasks/crawl-trending` | POST | 入队热榜抓取 |
| `/api/tasks/generate-recommendations` | POST | 入队推荐生成 |
| `/api/tasks/evaluate-recommendations` | POST | 入队每日评估（质量分 + 匹配度阈值） |
| `/api/tasks/daily-push` | POST | 入队每日推送（仅 `qualified`） |
| `/api/tasks/send-email-digest` | POST | 入队 Email 每日摘要（`user_id` / `limit` / `force`） |
| `/api/notifications/email/status` | GET | Email 通道状态与最近送达（脱敏） |
| `/api/notifications/email/test` | POST | 发送测试邮件（未启用 / 未配置 409） |
| `/api/tasks/send-telegram-digest` | POST | 入队 Telegram 每日摘要（M4-04，可选 `user_id` / `limit` / `force`） |
| `/api/notifications/telegram/status` | GET | Telegram 通道状态（不返回 token，chat id 脱敏） |
| `/api/notifications/telegram/test` | POST | 发送 Telegram 测试消息 |
| `/api/tasks/vectorize` | POST | 入队向量化（批量 / 增量 / 断点续跑） |
| `/api/tasks/{taskId}` | GET | 任务状态 |
| `/api/vector-index/sync` | POST | 入队 Vectorize 同步 / 对账（`kind` / `scope` / `force`） |
| `/api/vector-index/status` | GET | 本地向量覆盖率与同步状态分布 |
| `/api/vector-index/runs` | GET | 最近同步运行记录 |
| `/api/vector-index/runs/{runId}` | GET | 单次运行详情 |
| `/api/vectors/stats` | GET | 向量覆盖率与最近运行 |
| `/api/vectors/runs/{runId}` | GET | 向量化运行详情 |
| `/api/vectors/{source}/{repoId}` | GET | 单条仓库向量 |
| `/api/push/bark/status` | GET | Bark 通道状态与待投递 / 已投递 / 失败计数 |
| `/api/push/bark/test` | POST | 同步发送 Bark 测试通知 |
| `/api/push/bark/dispatch` | POST | 入队 Bark 投递（`user_id` / `limit` 可选） |
| `/api/push/records` | GET | 统一推送记录（通道 / 状态 / 时间 / 关键字 + 分页） |
| `/api/push/records/stats` | GET | 投递统计（分通道 / 分状态 / 回执 / 送达率） |
| `/api/push/records/{id}` | GET | 投递详情 + 回执时间线 |
| `/api/push/receipts` | POST | 写入送达回执（服务商 / 人工，幂等） |
| `/healthz` | GET | 健康检查 |

### 4.3 vps → edge（Vectorize 内部接口，`X-Internal-Token`）

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/internal/vectors/upsert` | POST | 批量写入向量（1~1000 条/批） |
| `/api/internal/vectors/check` | POST | 按 ID 批量查询元数据（≤100 条/批） |
| `/api/internal/vectors/delete` | POST | 批量删除向量（≤1000 条/批） |
| `/api/internal/vectors/stats` | GET | 索引统计 |
| `/api/internal/vectors/list` | GET | 分页列出 ID（孤儿对账；不支持时返回 501） |

## 5. 安全边界

- 浏览器侧仅持有 httpOnly 会话 Cookie（`of_session`），**不接触任何第三方 token**；
- GitHub access token 仅存在于 edge（换取用户信息后即弃）与 vps（同步任务使用，存服务端）；
- edge → vps 调用必须带 `X-Internal-Token`；vps 不直接对公网暴露业务接口；
- 所有密钥通过平台 secrets 注入，仓库内只有 `.env.example` 占位符。

## 6. 部署拓扑

| 组件 | 部署位置 | 说明 |
| --- | --- | --- |
| admin | Cloudflare Pages | `npm run build` 产物（`admin/dist`），SPA 回退 `_redirects` |
| edge | Cloudflare Workers | `wrangler deploy`；绑定 D1 / Vectorize |
| vps | 本地服务器 | uvicorn + celery worker + celery beat + redis + ollama |
| 数据 | D1 + VPS 本地 SQLite | D1 为主数据；VPS 侧为算力缓存/镜像 |
