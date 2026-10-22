# 实施计划 · REQ-202610-0905 README 摘要接入同步流程

> 需求：REQ-202610-0905（backlog M1-13）｜ 分支：`feat/req-202610-0905-readme-summary-sync`
> 依赖：M1-05 同步链路（本分支基于集成分支 `feat/req-202610-0746-writeback`）、M3-01 模型选型（未就绪，按可配置模型实现）

## 1. 目标

把仓库同步与 README 中文摘要打通，形成「同步 → 批量摘要 → 回写 D1 → 前端可见」的闭环：

1. **接入同步流程**：`sync_repositories` 完成 upsert 后，自动为新增 / 变化的仓库入队摘要任务；
2. **Ollama 降级链**：Ollama（本地）→ DeepSeek（可选云端）→ 清洗后原文截断，任何模型不可用都不抛异常；
3. **批量队列**：独立 Celery 任务 `summarize_readmes`，按批查询 / 逐条生成 / 分批提交，暴露 PROGRESS 进度；
4. **回写 D1**：VPS 批量完成后通过内部接口 `POST /api/repos/summaries` 回写 `my_repositories.readme_summary`；
5. **前端可见**：edge `/api/repos` 返回 `summary` 字段，admin 仓库列表展示摘要。

## 2. 现状与缺口

- `vps/app/services/summarizer.py` 已实现降级链，但从未被调用；
- `github_service.get_readme()` 已实现，但同步任务只写元数据，不抓 README；
- `my_repositories.readme_summary` 列已存在，但没有任何写入路径；
- 同步任务为一次性任务，缺少后续摘要队列与进度；
- edge / admin 不展示摘要。

## 3. 方案

### 3.1 VPS 摘要服务

新增 `vps/app/services/summary_pipeline.py`：

- `summarize_repositories(repo_ids=None, limit=200, batch_size=10, force=False, max_chars=800, progress=None)`：
  - 默认只选 `readme_summary` 为空的仓库，`force=True` 可重算；
  - 按 `stars DESC` 取最多 `limit` 条，按 `batch_size` 分批；
  - 每条：`get_readme` → `clean_readme` → `summarize_with_source`；
  - 每批提交 SQLite，失败不阻塞后续；返回 `total / processed / summarized / skipped / failed / sources`；
  - 通过 `progress` 回调上报阶段、进度与当前仓库，供 Celery `update_state(PROGRESS)` 使用。
- `writeback_summaries(items)`：配置 `EDGE_BASE_URL` 时批量回写 edge；失败只记录，不影响任务结果。

### 3.2 降级链增强

`vps/app/services/summarizer.py` 增加 `SummaryResult` 与 `summarize_with_source()`，保留原 `summarize()` 兼容：

- `ollama`：本地 Ollama，`keep_alive` 可配置（默认 2m，批量结束即卸载）；
- `deepseek`：可选云端（未配置 key 直接跳过）；
- `truncated`：清洗后原文截断 + 说明；
- `empty`：输入为空。

### 3.3 批量队列与同步接入

- 新增 Celery 任务 `app.tasks.jobs.summarize_readmes`（`bind=True`）：
  - 参数 `repo_ids / limit / batch_size / force / max_chars`；
  - `update_state(state="PROGRESS", meta={phase, processed, total, percent, current})`；
  - 完成后回写 edge，返回统计。
- `sync_repositories` 新增 `with_summary=True / summary_limit / summary_batch_size`：
  - 记录本次 upsert 的仓库 id，提交后 `summarize_readmes.delay(...)`；
  - 返回 `summaryTaskId`，同步任务本身不被摘要阻塞。
- 新增 API：`POST /api/tasks/summarize`、`POST /api/repos/summarize`（内部令牌鉴权）。

### 3.4 edge 回写接口

`POST /api/repos/summaries`（内部令牌）：

```json
{ "items": [{ "repoId": "owner/repo", "summary": "中文摘要" }] }
```

逐条 `UPDATE my_repositories SET readme_summary = ? WHERE id = ?`，返回 `{total, updated, skipped}`；单批最多 500 条。

### 3.5 前端可见

- edge `RepoItem` 增加 `summary` 字段（`readme_summary`）；
- admin `RepoItem` 增加可选 `summary`，仓库列表在描述下方展示摘要；
- 演示数据保持兼容（summary 可选）。

## 4. 2G 预算控制

| 控制项 | 默认值 | 说明 |
| --- | --- | --- |
| `SUMMARY_BATCH_SIZE` | 10 | 每批提交条数，控制内存峰值 |
| `SUMMARY_MAX_PER_RUN` | 200 | 单次任务上限，避免长时间占用 worker |
| `SUMMARY_DELAY_MS` | 500 | 每条之间的间隔，给 Ollama / 系统留出余量 |
| `OLLAMA_KEEP_ALIVE` | 2m | 批量结束自动卸载模型 |
| worker 并发 | 2（部署基线） | 摘要任务与同步任务串行排队，不额外加并发 |

模型仍由 `OLLAMA_MODEL` 配置；M3-01 完成选型后切换到 ≤2B 量化模型即可，无需改代码。

## 5. 文件清单

- `vps/app/services/summarizer.py`、`vps/app/services/summary_pipeline.py`
- `vps/app/tasks/jobs.py`、`vps/app/api/tasks.py`、`vps/app/api/repos.py`
- `vps/app/config.py`、`vps/app/schemas.py`
- `vps/.env.example`
- `edge/src/routes/repos.ts`、`edge/src/types.ts`
- `admin/src/features/repos/api.ts`、`admin/src/features/repos/index.tsx`
- `vps/tests/test_summary_pipeline.py`、`vps/tests/test_api.py`
- 文档：`docs/architecture/overview.md`、`docs/architecture/data-model.md`、`docs/planning/task-planning.md`、`docs/requirements/open-questions.md`、`vps/README.md`、`edge/README.md`

> 说明：当前集成分支尚无 `vps/app/runtime.py` 与 `deploy/` 模板（M1-01 / REQ-202610-0893 未合并），本需求不涉及；待其合并后再把新增环境变量补进部署模板。

## 6. 验证计划

- `cd vps && .venv/bin/pytest -q`：新增摘要服务 / 批量队列 / API 用例，全部通过；
- `cd edge && npm run typecheck`：0 error；
- `cd admin && npm run lint && npm run build && npm run test`：全绿；
- 手工验证：本地 SQLite 插入仓库 → 触发摘要任务（模型不可用）→ 摘要为截断降级文本 → 批量统计正确；配置 mock edge 时回写请求体正确。

## 7. 风险与待人工事项

1. **M3-01 未完成**：默认 `OLLAMA_MODEL` 仍可能超 2G 预算，本需求只保证可配置与降级，选型由 M3-01 切换；
2. **真实 GitHub 网络**：测试不访问网络，README 抓取用 mock；生产需 `GITHUB_TOKEN` 与可达的 GitHub API；
3. **edge 回写地址**：需在 VPS `.env` 配置 `EDGE_BASE_URL`，并与 edge `INTERNAL_TOKEN` 保持一致；
4. **D1 迁移**：本需求复用已有 `readme_summary` 列，无需新增迁移；
5. **PR 合并**：按项目流程推送 fork 并开 PR 至集成分支，待人工合并。
