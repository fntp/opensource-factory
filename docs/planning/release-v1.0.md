# OpenFactory v1.0.0 发布说明

> 发布日期：2026-10-22 ｜ 里程碑：M5 · 上线硬化 ｜ 需求：REQ-202610-0947（backlog M5-09）
>
> 版本口径：仓库级里程碑标签 `v1.0.0`；`admin` / `edge` / `vps` 三个子项目同步为 `1.0.0`，
> 后续仍按各自 SemVer 独立演进。

## 1. 发布范围

v1.0 完成 M5「上线硬化」全部 8 项能力，并把 M1~M4 的功能收敛到可部署、可监控、
可备份、可审计的基线：

| 编号 | 能力 | 主要交付 |
| --- | --- | --- |
| M5-01 | 正式部署 | `deploy/scripts/deploy-*.sh`、Cloudflare / Caddy 模板、部署工作流、冒烟脚本 |
| M5-02 | 本机一体化 | `LOCAL_MODE=1` 单进程托管 admin 构建产物 + `/local/api/*` 只读接口 |
| M5-03 | 监控与告警 | VPS `/api/monitoring/*`、edge `worker_metrics`、admin 监控页、4G/15G 资源红线 |
| M5-04 | 备份与恢复 | SQLite 快照 / 校验 / 恢复演练、D1 导出校验、保留策略与预算 |
| M5-05 | 安全加固 | 接口限流、内部令牌双令牌轮换、登录防护、安全响应头 |
| M5-06 | 资源预算 | `python -m app.resource_budget check` 实测 4G 内存 / 15G 磁盘 |
| M5-07 | 运维手册 | 部署 / 升级 / 回滚 / 故障处理 SOP、`ops-diagnose.sh` 诊断包 |
| M5-08 | 安全审计 | `python -m app.security_audit` 密钥 / 依赖 / 配置 / 响应头 / 隐私边界检查 |
| M5-09 | 验收与发布 | `vps/scripts/m5_acceptance.py`、`acceptance-m5.md`、本说明与 `v1.0.0` 标签 |

## 2. 升级步骤

```bash
# 1) 取发布标签
git fetch --tags origin
git checkout v1.0.0

# 2) 运行目录与配置（幂等；新增 MONITOR_* / BACKUP_* / LOCAL_* / RATE_LIMIT_* 键）
deploy/scripts/bootstrap-runtime.sh

# 3) 安装依赖并构建
cd vps && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && cd ..
cd admin && npm ci && npm run build && cd ..
cd edge && npm ci && npm run typecheck && cd ..

# 4) 三端部署（需 Q3 凭据；无凭据时先 dry-run）
deploy/scripts/preflight.sh --env-file /opt/openfactory/deploy.env --target all
deploy/scripts/deploy-all.sh --env-file /opt/openfactory/deploy.env

# 5) 发布后验证
deploy/scripts/smoke-test.sh --env-file /opt/openfactory/deploy.env --json
cd vps && .venv/bin/python scripts/m5_acceptance.py --strict
```

数据库变更由应用启动时 `init_db()` 幂等建表（新增 `monitoring_alerts` /
`monitoring_check_runs` 等表），无需手工迁移；edge 侧新增表结构见
`docs/assets/d1-schema.sql`，按 `deploy/scripts/deploy-edge.sh` 的远端迁移流程执行。

## 3. 回滚

1. **应用回滚**：`git checkout <上一个标签>` 后重跑 `deploy/scripts/deploy-all.sh`；
   systemd 单元与运行目录保持兼容。
2. **数据回滚**：按 `docs/guides/backup-restore.md` 使用
   `deploy/scripts/restore-sqlite.sh --name <snapshot> --force --stop-services` 恢复 SQLite；
   D1 使用 `wrangler d1 execute` 导入最近一次 `backup-d1.sh` 产物。
3. **本机一体化回退**：`sudo deploy/scripts/local-allinone.sh disable`，恢复混合架构。
4. **限流 / 令牌回退**：将 `RATE_LIMIT_ENABLED=0` 或回退 `INTERNAL_TOKEN` /
   `INTERNAL_TOKEN_PREVIOUS` 后重启 `openfactory-api`；轮换过渡期旧令牌仍可用。

回滚决策矩阵与故障分级见 `docs/guides/operations-runbook.md` §4–§7。

## 4. 验收与质量门禁

- 自动验收：`vps/scripts/m5_acceptance.py`（部署资产 / 本机模式 / 监控 / 备份 /
  安全 / 资源预算 / 运维手册 / 安全审计 / 版本一致性），报告见
  `docs/planning/acceptance-m5.md` 与 `acceptance-m5-report.{md,json}`；
- 三端检查：`vps` pytest、`edge` typecheck + 测试、`admin` lint + build + test；
- 安全审计：`python -m app.security_audit --root .. --json` 无 critical / high；
- 资源预算：`python -m app.resource_budget check --json` 判定 PASS（4G / 15G 红线内）。

## 5. 已知限制

- **M5-01 真实上线待 Q3 凭据**：Cloudflare 账号 / D1 / Pages / Workers、域名与
  GitHub OAuth 凭据未提供，v1.0 交付的是已验证的部署工具链与 dry-run；真实部署需按
  `docs/guides/production-deployment.md` 执行并补一次线上冒烟。
- **M4-09 验收仍在进行**：M4 推送链路的跨分支验收在另一工作树推进，不影响 v1.0 代码合并，
  但其验收报告尚未归档。
- **依赖锁定（Q22）**：`vps/requirements.txt` 仍为版本区间，安全审计以 medium 提示；
  生产环境建议按 `pip freeze` 生成锁定文件后再发布。
- **数据生命周期（Q23）**：用户数据导出 / 删除接口尚未落地，隐私边界审计以 medium 提示，
  计划在 M9-06 完成。
- **外部通道凭据（Q15 / Q16 / Q20）**：Telegram、Email、Workers Analytics 需真实凭据，
  本地验收以契约测试与降级路径覆盖。
- **备份 RTO / RPO（Q21）**：当前为每日备份 + 每周演练，具体 RTO / RPO 目标待运维确认。
