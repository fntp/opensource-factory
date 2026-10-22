# 实施计划 · 增量同步策略（REQ-202610-0899 / M1-07）

> 迭代：IT-0007 ｜ 依赖：M1-05 Starred 全量同步 ｜ 分支：`feat/req-202610-0899-incremental-sync`
>
> 目标：把 GitHub 资产同步从「每次全量拉取 + 全量写库」改为「按 `pushed_at` / Star 变化增量处理」，
> 降低同步耗时与 GitHub API 配额消耗，同时保留可手动触发的全量对账能力。

## 1. 现状与问题

- `vps/app/services/github_service.py` 的 `list_user_repos()` 每次分页拉取 `/user/repos` 与
  `/user/starred`，`normalize_repo()` 只保留 name / description / stars / language 等少量字段；
- `vps/app/tasks/jobs.py` 的 `sync_repositories()` 对返回的每个仓库逐行 `get` + 全字段覆盖写，
  即使内容没有变化也会产生 UPDATE；
- 没有同步水位线（checkpoint），无法只拉取上次同步后更新的仓库；
- 没有全量对账概念，Star 变化、取消 Star 等情况只能靠每次全量扫描兜底。

## 2. 方案设计

### 2.1 水位线与同步状态

新增本地表 `sync_state`（仅 VPS 本地镜像库，不进 D1）：

| 字段 | 说明 |
| --- | --- |
| `source` PK | `github:own` / `github:starred` |
| `last_synced_at` | 上次成功同步的 `updated_at` 高水位（ISO 8601） |
| `last_full_synced_at` | 上次全量对账时间 |
| `last_run_at` / `last_status` / `last_result` | 最近一次执行时间、状态与计数快照（JSON） |

水位线只在**成功**后推进；失败保留旧水位，下一次自动重试。

### 2.2 增量拉取

| 数据源 | 拉取方式 | 说明 |
| --- | --- | --- |
| 自有仓库 | `GET /user/repos?sort=updated&direction=desc&since=<checkpoint-60s>` | GitHub 服务端按 `updated_at` 过滤；留 60 秒重叠窗口，通常只需 1 页 |
| Starred | `GET /user/starred?sort=updated&direction=desc` 分页 | Starred 接口不支持 `since`；每页 100 条，只对变化行写库，请求量远低于逐仓库详情 |

### 2.3 变化判定

`my_repositories` 补充 `pushed_at` / `updated_at` / `synced_at` 字段（与 D1 扩展列对齐）。
对每条远端仓库与本地行比较：

- `pushed_at` 变化 → 有代码推送，更新；
- `stars` 变化 → Star 数变化，更新；
- 名称 / 描述 / 地址 / 语言 / forks / owner / `updated_at` 变化 → 更新；
- 全部一致 → `unchanged`，**不写库**。

### 2.4 全量对账

以下场景忽略水位线、扫描全部页：

1. 首次同步（无水位线）；
2. 距上次全量超过 `FULL_SYNC_INTERVAL_DAYS`（默认 7 天）；
3. 手动触发 `mode=full`（`POST /api/tasks/sync?mode=full`）。

全量对账用于补偿 Star 变化、取消 Star、删除仓库等增量路径难以发现的变化；不会自动删除本地行。

### 2.5 调度与接口

- Celery beat：每日 03:17 增量同步；每周日 04:07 全量对账；
- `POST /api/tasks/sync?mode=incremental|full`（默认 incremental）；
- `POST /api/repos/sync?mode=...` 同步支持；
- 任务返回值保持 `status/total/created/updated` 兼容，新增 `mode/since/unchanged/checkpoint/sources`。

## 3. 改动文件

| 文件 | 改动 |
| --- | --- |
| `vps/app/models.py` | `MyRepository` 增加 `pushed_at` / `updated_at` / `synced_at`；新增 `SyncState` |
| `vps/app/services/github_service.py` | `normalize_repo` 补充时间与 owner/forks；新增增量分页函数 |
| `vps/app/services/incremental.py` | 新增：变化判定、水位线、增量/全量编排 |
| `vps/app/tasks/jobs.py` | `sync_repositories` 改走增量服务，新增 `mode` 参数 |
| `vps/app/api/tasks.py` / `repos.py` | 同步接口支持 `mode` |
| `vps/app/tasks/celery_app.py` | 每日增量 + 每周全量 beat |
| `edge/migrations/0002_incremental_sync.sql` | D1 `my_repositories` 增加 `pushed_at` |
| `docs/assets/d1-schema.sql`、`docs/architecture/data-model.md` | Schema / 数据模型同步 |
| `vps/README.md`、`docs/architecture/overview.md` | 同步流程与接口说明 |
| `vps/tests/test_incremental_sync.py` | 纯函数 + 编排单测（不访问网络） |

## 4. 验证

```bash
cd vps && .venv/bin/pytest -q
cd edge && npm run typecheck
```

- 单测覆盖：首次全量、水位线增量、`pushed_at` 变化、Star 变化、无变化不写库、
  全量模式忽略水位线、抓取失败不推进水位线；
- 不访问网络：GitHub 拉取函数通过参数注入替换。

## 5. 风险与取舍

- Starred 无 `since` 参数，增量模式仍需扫描列表；但只写变化行，且列表每页 100 条，
  相比逐仓库详情 + 全量 UPDATE 已显著降低耗时与配额；
- 取消 Star / 删除仓库不做自动删除，避免误删用户资产；由全量对账报告差异，后续 M1-16
  对账工具处理；
- `sync_state` 为本地运行态，不参与 D1 主数据，避免边缘侧无意义写入。
