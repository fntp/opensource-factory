# 实施计划 · REQ-202610-0908 数据一致性巡检（D1 ↔ 本机镜像对账工具）

> 对应需求：REQ-202610-0908（backlog M1-16）｜ 分支：`feat/req-202610-0908-consistency-audit`｜ 日期：2026-10-22｜ 状态：已完成

## 1. 目标

提供一套可重复执行、可脚本化的对账工具，比较 Cloudflare D1（主数据）与本机 SQLite 镜像（算力缓存），回答三个问题：

1. 哪些记录只存在于 D1（本机缺失）？
2. 哪些记录只存在于本机（D1 缺失）？
3. 双方都存在的记录中，哪些字段值不一致？

工具需要能在无人值守场景（cron / systemd timer）运行，用退出码与报告文件暴露问题，并且不依赖 Cloudflare 账号密钥。

## 2. 现状与约束

- D1 为主数据，本机 SQLite 为可重建镜像（见 `docs/architecture/data-model.md` §6）；
- 本机无法直连 D1：生产凭据（Q3）未就绪，且不应把 Cloudflare Token 下发到 VPS；
- 两边表结构存在演进差异（D1 扩展列多于本地镜像），对账必须按**双方实际存在的列**取交集，避免把「本地没有该列」误报为字段差异；
- 数据量以个人资产为主（万级以内），全量拉取 + 内存比对足够，无需引入额外服务；
- 工具只读，不写 D1、不写本地库，避免巡检本身制造不一致。

## 3. 方案

### 3.1 总体链路

```text
edge GET /api/internal/consistency/snapshot   （X-Internal-Token，只读、分页）
        │  表名白名单 + 列白名单 + 主键排序
        ▼
vps/scripts/consistency_audit.py              （CLI，stdlib + 项目服务）
        │  --edge-url  ── 在线拉取 D1 快照
        │  --d1-db    ── 读取 wrangler d1 export 生成的 SQLite
        │  --snapshot ── 读取 JSON 快照（离线 / 归档）
        ▼
vps/app/services/consistency.py               （纯函数：归一化 / 对账 / 报告）
        │  按主键对齐；缺失、多余、字段差异、重复主键
        ▼
文本摘要 + Markdown 报告 + JSON 报告；退出码 0/1/2
```

### 3.2 D1 快照接口（edge）

- `GET /api/internal/consistency/snapshot?table=<name>&limit=&offset=`；
- 仅接受白名单表：`my_repositories` / `categories` / `trending_repositories` / `users` / `recommendations`；
- 仅返回白名单列，主键升序稳定排序，`limit` 默认 500、上限 1000；
- 鉴权：`X-Internal-Token` 必须等于 `INTERNAL_TOKEN`；未配置时返回 503（默认关闭），不暴露任何数据；
- 返回 `{table, columns, rows, offset, limit, total, hasMore, generatedAt}`。

### 3.3 对账逻辑（vps）

- 表规格内置主键、字段类型与本地列别名（如 D1 `users.login` ↔ 本地 `users.username`）；
- **可比字段 = 表规格 ∩ D1 实际列 ∩ 本地实际列**，跳过的字段在报告中列明原因；
- 归一化：
  - 文本：`None` → 空串，去除首尾空白；
  - 整数 / 浮点：空值按字段默认值（如 `stars=0`），浮点保留 6 位；
  - 时间：统一为 `YYYY-MM-DDTHH:MM:SS`（UTC，忽略小数秒）；
- 对账结果：`missingInLocal` / `missingInD1` / `mismatches`（字段级）/ `duplicateKeys`；
- 支持 `--ignore-fields table.field` 排除已知噪声字段（如 `synced_at`）。

### 3.4 CLI

```bash
cd vps
.venv/bin/python scripts/consistency_audit.py \
  --edge-url https://<worker-domain> --token "$INTERNAL_TOKEN" \
  --report /opt/openfactory/logs/consistency-report.md \
  --json-out /opt/openfactory/logs/consistency-report.json
```

- 数据源三选一：`--edge-url` / `--d1-db` / `--snapshot`；
- `--local-db` 默认读取 `DATABASE_URL`，否则 `vps/data/opensource_factory.db`；
- `--tables` 默认五张核心表；`--sample-limit` 控制每类差异的样例条数；
- 退出码：`0` 一致，`1` 发现差异，`2` 输入 / 连接错误（便于 cron 告警）；
- 报告包含汇总表、逐表差异样例与跳过字段说明。

### 3.5 测试

- `vps/tests/test_consistency_audit.py`：
  - 归一化（时间 / 数字 / 空值）；
  - 一致、缺失、多余、字段差异、重复主键；
  - 列交集与别名映射；
  - JSON 快照三种格式解析；
  - CLI 端到端（临时 SQLite 作本地库与 D1 导出库，断言退出码与报告内容）；
  - edge 快照接口分页拉取（本地 HTTP stub，不访问外网）。

## 4. 文件清单

| 文件 | 说明 |
| --- | --- |
| `edge/src/routes/consistency.ts` | 内部只读快照接口（白名单 + 分页 + 令牌） |
| `edge/src/index.ts` | 挂载 `/api/internal/consistency` |
| `vps/app/services/consistency.py` | 表规格、归一化、对账、报告渲染、快照加载 |
| `vps/scripts/consistency_audit.py` | 命令行入口 |
| `vps/tests/test_consistency_audit.py` | 单元 + CLI 集成测试 |
| `docs/guides/data-consistency-audit.md` | 使用手册 / 巡检 SOP |
| `docs/architecture/overview.md` | 接口边界补充内部快照接口 |
| `docs/architecture/data-model.md` | 一致性约定补充对账工具 |
| `vps/README.md` / `edge/README.md` | 子项目说明 |
| `docs/README.md` / `docs/planning/task-planning.md` | 文档索引与排期同步 |
| `docs/planning/plan-req-202610-0908-consistency-audit.md` | 本计划 |

## 5. 验收标准

1. `edge npm run typecheck` 通过；
2. `vps .venv/bin/pytest -q` 全绿，新增用例覆盖对账核心与 CLI 退出码；
3. 用两份临时 SQLite（模拟 D1 导出 / 本地镜像）跑 CLI，能正确报告缺失、多余与字段差异；
4. 快照接口未配置令牌返回 503、错误令牌返回 401、合法令牌可分页拉取；
5. 文档同步完成，无密钥入库。

## 6. 风险与边界

- 快照接口依赖 `INTERNAL_TOKEN` 与 Worker 可达；不可达时 CLI 可用 `--d1-db` / `--snapshot` 离线对账；
- 对账只比较双方都有的列；D1 新增列未镜像到本地时会在 `skippedFields` 中提示，不视为差异；
- 全量拉取适用于万级数据；数据量继续增长后可改为按主键游标分页（接口已支持 offset/limit）；
- 本需求不自动修复数据，修复动作由后续数据治理需求（M9-05）承接。
