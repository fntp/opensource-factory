# M5 验收与发布 v1.0（REQ-202610-0947）

> 验收日期：2026-10-22 ｜ 分支：`feat/req-202610-0947-m5-acceptance`
>
> 关联需求：`docs/requirements/backlog.md` · M5-09（M5 · 上线硬化）｜ 依赖：M5-01~08
>
> 自动报告：`acceptance-m5-report.md` / `acceptance-m5-report.json`（由 `vps/scripts/m5_acceptance.py` 生成）

## 1. 结论

M5-01~M5-08 已全部集成到验收分支，跨分支端到端验收 **29/29 PASS**，
三端检查全部通过，仓库级里程碑标签 `v1.0.0` 打在本次验收提交上：

| 检查 | 结果 |
| --- | --- |
| VPS pytest | **421 passed**（10 warnings，无失败） |
| Edge `tsc --noEmit` | 通过 |
| Edge `node --test scripts/*.test.mjs` | **61 passed** |
| Admin `eslint .` | 通过 |
| Admin `tsc -b && vite build` | 通过 |
| Admin Vitest（headless） | **117 passed**（17 files） |
| M5 验收脚本 | **29 PASS / 0 FAIL / 0 SKIP** |
| 安全审计 | `WARN`（critical 0 / high 0 / medium 2） |
| 资源预算 | `PASS`（内存 43.7 / 4096 MB，磁盘 593.4 / 15360 MB） |

验收环境：Linux x86_64 · Python 3.12.3 · 临时 SQLite + 临时运行目录 +
真实 `uvicorn`（主进程 / `LOCAL_MODE=1` 各一轮）· 部署资产 dry-run。

## 2. 验收矩阵

| 编号 | 能力 | 验收方式 | 结果 |
| --- | --- | --- | --- |
| M5-01 | 正式部署工具链 | 19 个部署脚本可执行 + `bash -n`；systemd 4 单元基线；wrangler / Caddy 模板渲染 600；preflight / smoke dry-run；CI 门禁 | PASS（真实上线待 Q3） |
| M5-02 | 本机一体化 | 默认 `LOCAL_MODE=0` 时 `/local/api/*` 全 404；`LOCAL_MODE=1` 时首页 / SPA 回退命中 admin 构建产物，`/local/api/*` 返回单用户只读数据 | PASS |
| M5-03 | 监控与告警 | `/api/monitoring/status`、`/check`、`/history`、`/alerts`、`/alerts/{id}/ack`、`/logs`、`/logs/cleanup` 全契约；告警注入 / 确认闭环 | PASS |
| M5-04 | 备份与恢复 | SQLite 快照创建、完整性校验（5 项 / 21 张表）、恢复演练（21 张表行数一致）、产物列表与保留策略 | PASS |
| M5-05 | 安全加固 | 双令牌状态与旧令牌可用、错误令牌 401、连续请求 429 + `Retry-After`、安全响应头基线 | PASS |
| M5-06 | 资源预算 | `python -m app.resource_budget check --json`：4G / 15G 红线判定 PASS，4 个 systemd 单元上限齐全 | PASS |
| M5-07 | 运维手册 | 7 份运维指南齐全，runbook 含巡检 / 升级 / 回滚 / 故障 / 备份 / 密钥轮换；诊断脚本帮助可用 | PASS |
| M5-08 | 安全审计 | `python -m app.security_audit --root .. --json`：critical 0 / high 0，7 项检查完成 | PASS（medium 2 见遗留） |
| M5-09 | 验收与发布 | 本文件 + 计划 + 自动报告 + 版本 1.0.0 + `v1.0.0` 标签 | PASS |

## 3. 集成修复记录

本轮合并 0939~0946 八个分支时发现并修复：

1. **重复模型与旧任务回潮**：多个分支重复引入 `SummaryQualitySample`，并在
   `regenerate_recommendation_reasons` 中恢复已删除的 edge 推送 / `pushed` 返回值；
   逐次保留单一模型定义与 M4 既有行为。
2. **`PushReceipt.created_at` 丢失**：M4-08 回执服务按 `occurred_at, created_at` 排序，
   合并后模型缺少 `created_at`，4 个回执用例失败；已恢复该列。
3. **`recommend.py` 缺少 `json` 导入**：M4-01 质量明细解析在合并后 `NameError`；
   已补齐导入。
4. **内部令牌测试架构漂移**：M5-05 把 `require_internal_token` 收敛到
   `app.security`，旧测试仍 monkeypatch `app.api.tasks.get_settings`；已改为
   `app.security.get_settings`，覆盖 monitoring / push policy / push records / telegram。
5. **安全审计误报**：`privacy-log` 规则把中文提示语「Email 摘要任务完成」当成敏感字段输出，
   导致 `test_current_repository_has_no_high_findings` 失败；已改为先剥离字符串字面量、
   再检查 f-string 内插表达式，并保留 `logger.info("token=%s", token)` 的检出。
6. **文档编号收敛**：`task-planning.md` 的 IT-0035~0042 去重排序，
   `open-questions.md` 的 Q14 重复项重排为 Q18~Q23，架构文档章节重新编号。

## 4. 资源与性能抽样

| 场景 | 结果 | 预算 |
| --- | --- | --- |
| 资源预算 CLI（内存） | 43.7 MB 实测 / 1347.9 MB 预估峰值 | 4096 MB |
| 资源预算 CLI（磁盘） | 593.4 MB（含 node_modules） | 15360 MB |
| systemd 单元上限 | api 384M / worker 768M / beat 192M / redis 320M | 合计 1664M |
| M5 验收脚本总耗时 | 约 12s（含两轮 uvicorn 启动） | — |

本机为临时 SQLite + 本地回环 HTTP，性能数据仅代表开发机基线；
生产环境需按 `docs/guides/resource-budget-verification.md` 复测。

## 5. 回顾

### 做得好的

- 八个分支按依赖顺序合并，M5-01/02 基础层先行，M5-03~08 在其上叠加，
  冲突集中在 `config.py` / `schemas.py` / `models.py` / 文档，业务实现基本独立。
- 验收脚本复用 M3 的真实 HTTP + 临时数据库模式，额外覆盖部署资产 dry-run 与
  `LOCAL_MODE` 双进程，不依赖 Cloudflare / 域名 / 外部凭据即可重复执行。
- 安全审计从「阻断发布」变成可解释的门禁：critical / high 为 0，medium 项与
  Q22 / Q23 一一对应，不再用误报掩盖真实风险。

### 需要改进的

- 多分支并行修改 `models.py` 时仍会丢列（`PushReceipt.created_at`），
  合并后必须跑完整 pytest 而不是只跑增量用例。
- M5-05 重构 `require_internal_token` 后没有同步更新其他分支的测试补丁点，
  说明跨分支重构需要 grep 全仓测试引用。
- 资源预算的磁盘口径包含本机 `node_modules`，与生产运行目录口径不同，
  报告需明确区分「代码检出」与「运行目录」。

## 6. 复跑方式

```bash
# VPS：完整测试 + M5 验收（在 vps/ 下，使用项目 venv）
pytest -q
python scripts/m5_acceptance.py --strict \
  --report-md docs/planning/acceptance-m5-report.md \
  --report-json docs/planning/acceptance-m5-report.json

# Edge
cd edge && npm ci && npm run typecheck && npm test

# Admin
cd admin && npm ci && npm run lint && npm run build && npm test
```

## 7. 遗留事项

- **M5-01 真实上线待 Q3 凭据**：Cloudflare 账号 / D1 / Pages / Workers、域名与
  GitHub OAuth 凭据未提供，本次验收只覆盖工具链与 dry-run；上线后需补一次
  `deploy-all.sh` + `smoke-test.sh` 线上冒烟。
- **M4-09 验收仍在进行**：M4 推送链路验收在另一工作树推进，报告尚未归档；
  不影响 v1.0 代码合并，但发布说明需保持「M4 验收未闭环」的表述。
- **安全审计 medium 2 项**：`dependency-lock`（Q22，`requirements.txt` 未锁定）与
  `privacy-lifecycle`（Q23，用户数据导出 / 删除接口未落地），计划分别在发布前
  锁定依赖、M9-06 完成数据生命周期。
- **备份 RTO / RPO（Q21）**：当前每日备份 + 每周演练，具体目标待运维确认。
