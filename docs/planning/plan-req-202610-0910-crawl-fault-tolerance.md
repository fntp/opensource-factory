# 实施计划 · REQ-202610-0910 抓取容错与页面结构变更告警

> 需求：REQ-202610-0910（backlog M2-02，依赖 M2-01）｜ 分支：`feat/req-202610-0910-crawl-fault-tolerance`
> 目标：热榜抓取遇到网络抖动、限流、页面改版时**降级为空列表 + 日志，不抛异常**，并把「页面结构疑似变更」沉淀为可查询、可确认的告警。

## 1. 现状与问题

- `trending_crawler.py` 的解析器对缺字段、单行异常已容错，但 HTTP 请求只尝试一次：
  - 网络超时 / 连接错误 / 429 / 5xx 直接返回空列表，容易把偶发抖动误判为「页面无数据」；
- 抓取任务没有区分「请求失败」与「页面结构变更」：
  - 页面返回 200 但解析结果为 0 条时，只写一行 warning，无法判断是改版还是临时空页；
- 没有告警落库与查询入口，值班人员只能翻日志；
- M2-01 已提供页面级统计（`pages[].ok / count / error`）与 `failedPages`，本需求在其上补齐重试、结构变更判定与告警闭环。

## 2. 方案

### 2.1 抓取重试（crawl_guard.py）

新增 `vps/app/services/crawl_guard.py`，与具体站点解耦：

- `CrawlRetryPolicy`：最大尝试次数、指数退避基数、单次等待上限；
- `is_transient_status()`：仅 429 / 5xx 视为可重试；
- `fetch_html_with_retry()`：对 `httpx.HTTPError`、429、5xx 重试，429 优先使用 `Retry-After`；
  最终失败返回结构化 `FetchResult`（状态码 / 文本 / 错误 / 尝试次数），**不抛异常**；
- 配置项：`TRENDING_RETRY_MAX`（默认 3）、`TRENDING_RETRY_BASE_DELAY`（1.0s）、
  `TRENDING_RETRY_MAX_DELAY`（8.0s）。

### 2.2 页面结构变更判定

在 `trending_crawler.py` 增加解析诊断（不改动原有 `parse_trending_html` 契约）：

- `ParseReport(rows, parsed, dropped)`：页面候选行数、成功解析数、丢弃数；
- `parse_trending_html_with_report(html)` 同时返回条目与诊断；
- 判定规则（`crawl_guard.evaluate_page_health`）：
  | 条件 | 告警类型 | 说明 |
  | --- | --- | --- |
  | HTTP 重试后仍失败 | `fetch_failed` | 网络 / 限流 / 5xx |
  | 200 且候选行数 = 0 | `structure_change` | 页面无 `article` 结构，疑似改版 |
  | 200 且候选行 > 0、解析数 = 0 | `structure_change` | 选择器失配 |
  | 解析数 < 上次成功数 × `TRENDING_COUNT_DROP_RATIO`（默认 0.3，基线 ≥ 5） | `count_drop` | 结构局部变更或页面异常 |
  | 整轮 0 条且存在失败页 | `all_failed` | 整轮不可用 |

### 2.3 告警落库、去重与通知

新增两张本地表（`init_db()` 自动建表，兼容既有 SQLite）：

- `crawl_page_stats`：按「平台 + 页面」记录上次成功条数 / 时间 / 最近错误，作为结构变更基线；
- `crawl_alerts`：`id / platform / page / kind / severity / message / details(JSON) / dedupe_key /
  status(open|acknowledged) / occurrences / first_seen_at / last_seen_at / acknowledged_at`。

去重：同一 `platform:page:kind` 在冷却窗口（`TRENDING_ALERT_COOLDOWN_MINUTES`，默认 360）内
重复出现时累加 `occurrences` 并刷新 `last_seen_at`，不重复插入。

通知：配置 `TRENDING_ALERT_WEBHOOK_URL` 时，落库后 best-effort POST 一条 JSON；
未配置或请求失败只记日志，不影响抓取任务。

### 2.4 API 与任务接入

- `GET /api/trending/alerts?status=open&limit=50`：告警列表（按最近出现倒序）；
- `POST /api/trending/alerts/{id}/ack`：人工确认，置为 `acknowledged`；
- `crawl_trending` 在 upsert 后调用 `process_crawl_health()`：
  - 逐页判定并写告警 / 更新页面基线；
  - 任何告警处理异常都只记录日志，**不改变抓取结果、不向上抛异常**；
  - 返回值追加 `alerts` 统计（新增 / 重复 / 已确认）。

### 2.5 降级契约

- 单页失败 → 该页空列表，其他页继续；
- 全部页面失败 → 返回 `status=error`、`total=0`，任务本身成功返回（Celery 不重试整轮）；
- 解析异常 → 空列表 + `structure_change` 告警；
- 告警落库 / webhook 失败 → 只记日志，绝不影响抓取主流程。

## 3. 文件清单

- `vps/app/services/crawl_guard.py`（新增）
- `vps/app/services/trending_crawler.py`（重试 + 解析诊断）
- `vps/app/tasks/jobs.py`（任务接入健康检查）
- `vps/app/models.py`（`CrawlAlert` / `CrawlPageStat`）
- `vps/app/schemas.py`（告警 DTO）
- `vps/app/api/trending.py`（告警查询 / 确认）
- `vps/app/config.py`、`vps/.env.example`（重试 / 告警配置）
- `vps/tests/test_crawl_guard.py`、`test_crawl_alerts.py`（新增）
- 文档：`docs/architecture/data-model.md`、`overview.md`、`vps/README.md`、
  `docs/planning/task-planning.md`、`docs/requirements/backlog.md`

## 4. 验证计划

| 检查 | 内容 |
| --- | --- |
| `vps .venv/bin/pytest -q` | 重试（超时 / 429 / 5xx / 4xx 不重试）、结构变更、去重、webhook 降级、API 用例 |
| `edge npm run typecheck` | 确认 VPS 契约新增字段不影响边缘类型 |
| `git diff --check` | 空白与格式检查 |
| 手工 | 空 HTML / 选择器失配 HTML → 告警落库；同页重复失败 → occurrences 累加 |

测试不访问网络：HTTP 使用 fake client，webhook 默认关闭。

## 5. 交付边界

- 本需求不改变热榜解析字段与入库结构（属 M2-01 / M2-05）；
- 不实现推送通道（Bark / Telegram / Email 属 M4），只提供告警表、查询接口与通用 webhook；
- 页面结构变更的「自动修复选择器」不在范围内，只做检测与告警。
