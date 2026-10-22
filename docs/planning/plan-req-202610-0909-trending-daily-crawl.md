# 实施计划 · REQ-202610-0909 GitHub Trending 每日定时抓取（Celery beat，多语言页）

> 需求：REQ-202610-0909（backlog M2-01，依赖 M1-01）｜ 分支：`feat/req-202610-0909-trending-daily-crawl`
> 目标：由 Celery beat 每日定时抓取 GitHub Trending 全局页 + 多语言页，解析后去重入库，形成可持续的热榜数据源。

## 1. 现状与问题

- `vps/app/services/trending_crawler.py` 已有 fixture 驱动的解析器（`parse_trending_html`）与单页抓取入口；
- `vps/app/tasks/celery_app.py` 当前每 6 小时抓一次，且只抓全局页（`language=None`），不满足「每日 + 多语言页」；
- `crawl_trending` 只按单页 upsert，未持久化 `owner` / `language` / `stars`（D1 schema 已预留这些列）；
- 单个语言页失败会拖垮整轮抓取，缺少页面级统计与降级结果。

## 2. 方案

### 2.1 抓取层（trending_crawler.py）

- `build_trending_url(language, since)`：生成 `https://github.com/trending[/<language>]?since=daily`，语言 slug 做 URL 编码；
- `normalize_languages()`：支持逗号分隔字符串 / 序列，去空、去重、小写；
- `crawl_github_trending_pages()`：全局页 + 配置语言页**顺序**抓取（页间默认 1s，避免触发 GitHub 限流），单页失败仅记录，不中断整轮；
- `merge_trending_items()`：按 `owner/repo` 去重合并，缺失字段互补，`stars` / `stars_today` 取较大值，保留来源语言页列表；
- 保留 `crawl_github_trending()` 单页入口（向后兼容），支持注入 `httpx.AsyncClient` 便于离线测试。

### 2.2 任务层（jobs.py）

- `crawl_trending` 新增 `languages`（逗号分隔或列表）与 `since` 参数；未显式指定语言时使用 `TRENDING_LANGUAGES` 配置；
- 指定 `language` 时仍只抓单页（兼容既有调用）；
- 返回页面级统计：`pages[]`（language / count / ok / error）与 `failedPages[]`；
- 状态语义：全部成功 `ok`，部分页面失败 `partial`，全部失败且无数据 `error`（不抛异常）；
- upsert 补齐 `owner` / `language` / `stars`，技术栈由描述 + 语言提取。

### 2.3 定时计划（celery_app.py）

- 将 `crawl-trending-every-6h` 改为 `crawl-trending-daily`，默认每天 `03:27`（Asia/Shanghai），小时 / 分钟可由配置覆盖；
- beat kwargs 传入 `languages=TRENDING_LANGUAGES`，实现多语言页定时抓取；
- 保留每日 09:00 推送准备任务。

### 2.4 配置与存储

- `Settings` 新增 `TRENDING_LANGUAGES`、`TRENDING_CRAWL_HOUR`、`TRENDING_CRAWL_MINUTE`，同步 `vps/.env.example`；
- `TrendingRepository` 增加 `owner` / `language` / `stars` 列；`init_db()` 对既有 SQLite 库幂等补列；
- `TrendingRepoOut` 输出上述字段，`/api/tasks/crawl-trending` 与 `/api/trending/crawl` 支持 `languages` / `since`。

## 3. 默认语言页

`python, javascript, typescript, go, rust, java, cpp, c, php, ruby, swift, kotlin`（可通过 `TRENDING_LANGUAGES` 覆盖，留空则只抓全局页）。

## 4. 测试与验证

| 检查 | 内容 |
| --- | --- |
| `pytest -q` | 解析器回归 + 多语言抓取（MockTransport）+ 去重合并 + 任务落库 + beat 计划 |
| `npm run typecheck`（edge） | 确认 VPS 契约改动未影响边缘类型（本需求不改 edge） |
| `git diff --check` | 空白与格式检查 |

## 5. 交付边界

- 本需求只做「抓取 + 定时 + 入库」，按日快照 / 趋势字段属 M2-05，页面日期 / 语言筛选属 M2-06；
- 页面结构变更告警属 M2-02，本需求先提供 `failedPages` 与日志作为基础信号；
- 测试不访问网络，真实抓取由部署后的 Celery beat 执行。

## 6. 验证记录

2026-10-22 本机：

- `cd vps && .venv/bin/pytest -q`：34 passed（新增多语言抓取 / 去重合并 / 任务落库 / beat 计划 / 旧库补列共 14 条）；
- `cd edge && npm run typecheck`：0 error（本需求未改 edge，确认契约无影响）；
- `git diff --check`：通过；`python -m compileall`：通过；
- 未执行真实 GitHub 网络抓取（测试要求不访问网络）；部署后由 `crawl-trending-daily` 每日 03:27 触发。
