# 实施计划 · 自有仓库与组织仓库同步（fork / 归档过滤策略）

> 需求编号：REQ-202610-0898（backlog M1-06）｜ 依赖：M1-05 ｜ 分支：`feat/req-202610-0898-repo-sync-policy`
> 编写时间：2026-10-22 ｜ 维护人：fntp

## 1. 需求理解

在既有 GitHub 仓库同步链路上补齐「自有仓库 + 组织仓库」的同步范围，并提供**可配置的过滤策略**：

- 同步范围：`GET /user/repos?affiliation=owner,organization_member`（本人 owner 的仓库 + 作为组织成员可见的组织仓库）；
- 过滤维度：
  - 是否包含自有仓库（`owner.type != Organization`）；
  - 是否包含组织仓库（`owner.type == Organization`）；
  - 是否包含 fork 仓库（`fork = true`）；
  - 是否包含已归档仓库（`archived = true`）；
  - 组织白名单（为空表示全部组织，配置后仅同步名单内组织）。
- 过滤策略既可**部署级配置**（环境变量），也可**单次任务覆盖**（接口 query 参数），默认：含自有 + 含组织、排除 fork、排除归档。

Starred 仓库属于用户主动收藏，不受上述「自有/组织」过滤策略影响（仍按 M1-05 链路全量同步）。

## 2. 现状与差距

| 现状 | 差距 |
| --- | --- |
| `vps/app/services/github_service.py` 已有 `/user/repos` + `/user/starred` 分页拉取与降级 | 未显式指定 `affiliation`，默认会混入 collaborator 仓库；无 fork / archived 过滤 |
| `normalize_repo` 仅保留 id/name/description/url/stars/language | 丢失 `owner`、`fork`、`archived`、`forks_count`、`updated_at`，无法过滤与对账 |
| `MyRepository` 本地模型缺少 D1 已扩展的 `owner` / `forks` / `updated_at` / `synced_at` 列 | 本地镜像与 D1 schema 漂移 |
| `/api/tasks/sync`、`/api/repos/sync` 仅支持 `include_starred` | 无法按需调整过滤策略 |
| 同步任务只返回 total/created/updated | 无法观察过滤了多少、各类原因分布 |

## 3. 实现设计

### 3.1 过滤策略模型（`vps/app/services/github_service.py`）

- 新增 `RepoFilterPolicy`（dataclass）：
  - `include_own: bool = True`
  - `include_orgs: bool = True`
  - `include_forks: bool = False`
  - `include_archived: bool = False`
  - `org_allowlist: tuple[str, ...] = ()`
- `evaluate(repo) -> str | None`：返回 `None` 表示保留，否则返回排除原因
  （`own_disabled` / `org_disabled` / `org_not_allowed` / `fork` / `archived`）。
- `from_settings(settings)`：从 `GITHUB_SYNC_*` 环境变量构建；`org_allowlist` 逗号分隔、大小写不敏感。
- `normalize_repo` 扩展字段：`owner`、`owner_type`、`forks`、`fork`、`archived`、`private`、`updated_at`、`pushed_at`。

### 3.2 拉取与统计（`github_service.py`）

- 新增 `RepoCollection`：`repos` / `fetched` / `starred` / `excluded`（按原因计数）/ `own` / `org`。
- 新增 `collect_user_repos(token, include_starred, policy, ...) -> RepoCollection`：
  - `/user/repos` 显式携带 `affiliation`（根据 include_own / include_orgs 组合）与 `visibility=all`；
  - 对自有/组织仓库应用过滤策略并统计；
  - Starred 不做策略过滤，单独计数；
  - 支持注入 `httpx` transport，便于无网络单测。
- 保留 `list_user_repos(...) -> list[dict]` 兼容包装（返回过滤后的列表）。

### 3.3 配置（`vps/app/config.py` + 环境模板）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `GITHUB_SYNC_INCLUDE_OWN` | `true` | 是否同步本人 owner 的仓库 |
| `GITHUB_SYNC_INCLUDE_ORGS` | `true` | 是否同步组织仓库 |
| `GITHUB_SYNC_INCLUDE_FORKS` | `false` | 是否包含 fork |
| `GITHUB_SYNC_INCLUDE_ARCHIVED` | `false` | 是否包含已归档 |
| `GITHUB_SYNC_ORG_ALLOWLIST` | 空 | 组织白名单，逗号分隔；空 = 全部 |

同步更新 `vps/.env.example`。

> 说明：本分支基线（`9e6c105`）尚未包含 REQ-202610-0893 的 `deploy/` 与 `vps/app/runtime.py`；
> 该基线合入后需把 5 个 `GITHUB_SYNC_*` 键补进 `deploy/env/openfactory.env.example` 与
> `vps/app/runtime.py::REQUIRED_ENV_KEYS`（模板一致性测试会校验），已列入遗留事项。

### 3.4 持久化（`vps/app/models.py` / `db.py` / `jobs.py`）

- `MyRepository` 增加 `owner` / `forks` / `updated_at` / `synced_at`，与 D1 `my_repositories` 扩展列对齐；
- `init_db()` 对 SQLite 做幂等补列（`PRAGMA table_info` + `ALTER TABLE`），避免既有本地库因缺列报错；
- `sync_repositories` upsert 时写入上述字段，并在每次同步刷新 `synced_at`；
- 任务返回增加 `own` / `org` / `starred` / `filtered` 统计。

### 3.5 接口（`vps/app/api/tasks.py` / `repos.py`）

- `/api/tasks/sync` 与 `/api/repos/sync` 增加可选 query：
  `include_own` / `include_orgs` / `include_forks` / `include_archived`（缺省走环境配置）。
- 保持 `202 {"taskId": ...}` 契约不变。

## 4. 文档同步

- `vps/README.md`：环境变量表 + 同步接口说明；
- `docs/architecture/overview.md`：同步流补充自有/组织与过滤策略；
- `docs/architecture/data-model.md`：说明本地镜像已落地扩展列；
- `docs/requirements/open-questions.md`：新增 Q10（组织范围与默认过滤口径）；
- `docs/planning/task-planning.md`：登记本轮迭代与交付记录；
- 本计划文档：记录实施范围、测试计划与遗留事项。

## 5. 测试计划

| 用例 | 覆盖点 |
| --- | --- |
| `test_github_service.py::test_normalize_repo_keeps_filter_fields` | 元数据字段完整 |
| `test_github_service.py::test_policy_*` | 自有/组织开关、fork/归档、白名单、组合优先级 |
| `test_github_service.py::test_collect_user_repos_uses_affiliation_and_filters` | 请求参数、分页、过滤统计、Starred 不过滤 |
| `test_sync_policy.py::test_sync_repositories_persists_metadata_and_stats` | upsert 落库 owner/forks/updated_at、过滤统计 |
| `test_sync_policy.py::test_sync_api_forwards_policy_overrides` | 接口 query 覆盖透传 |
| `test_deploy_assets.py`（既有） | 环境模板 / Settings / runtime 键集合一致 |

## 6. 风险与取舍

1. **历史数据**：过滤只影响本次同步写入，不删除历史行；若需清理已归档存量，另行以数据治理需求（M9-05）处理。
2. **组织私有仓库**：需 token 具备 `read:org` / `repo` 范围；缺失时 GitHub 只返回可见的公开组织仓库，不报错。
3. **本地 SQLite 补列**：仅做新增列，不改列类型；生产库首次启动自动补齐，幂等。
4. **与 M1-05 并行**：本需求复用同一 `github_service`；实现保持向后兼容（`list_user_repos` 签名不变），降低合并冲突。

## 7. 验收口径

- 默认策略下：fork 与 archived 仓库不进入同步结果；自有 + 组织仓库均被拉取；
- 环境变量或接口参数可切换五类策略，任务结果能给出过滤统计；
- `cd vps && .venv/bin/pytest -q` 全绿；
- 文档与环境模板同步，无密钥入库。
