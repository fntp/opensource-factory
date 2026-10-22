# 实施计划 · REQ-202610-0947 · M5 验收与发布 v1.0

> 文档编号：PL-REQ-0947 ｜ 维护人：fntp ｜ 创建日期：2026-10-22
>
> 关联需求：`docs/requirements/backlog.md` · M5-09（M5 · 上线硬化）｜ 依赖：M5-01~08
>
> 里程碑口径：仓库级 `v1.0.0` 标签；三个子项目各自保持独立 SemVer。

## 1. 目标与范围

把 M5 已完成的 8 个上线硬化能力整合到一条可交付验收分支，做一次跨分支端到端验收，
修复集成问题，把验收矩阵、原始报告、发布说明与复跑方式固化为文档，并在验收提交上
打仓库级里程碑标签 `v1.0.0`。

范围：

- 验收对象：正式部署工具链、本机一体化、监控告警、备份恢复、安全加固、
  资源预算、运维手册、安全审计；
- 集成对象：0939（M5-01）、0940（M5-02）、0941（M5-03）、0942（M5-04）、
  0943（M5-05）、0944（M5-06）、0945（M5-07）、0946（M5-08）；
- 不在本轮范围：真实 Cloudflare / 域名 / OAuth 上线（Q3 凭据未提供）、
  真实 D1 导出与线上恢复演练、生产环境压测；由部署工具链的 dry-run 与本地替身覆盖。

## 2. 实施步骤

1. 从 `origin/main` 拉出 `feat/req-202610-0947-m5-acceptance` 工作树；
2. 按依赖顺序 `git merge --no-ff` 集成 0939~0946，解决 `config.py`、`schemas.py`、
   `runtime.py`、`models.py`、`tasks/jobs.py`、`edge/src/index.ts`、`docs/*` 的交汇冲突，
   保留能力超集与 M4 已有行为；
3. 修复集成暴露的问题（重复模型、旧任务返回值回潮、安全审计误报等）；
4. 新增 `vps/scripts/m5_acceptance.py`：校验部署资产 / 运行目录 / 监控 / 备份 /
   安全 / 资源预算 / 运维手册 / 安全审计八组验收点，支持 `--strict`、
   `--report-md`、`--report-json`；
5. 版本号统一升至 `1.0.0`（admin / edge / vps / 环境模板），写发布说明；
6. 串行跑三端检查：vps pytest、edge typecheck / 测试、admin lint / build / test；
7. 生成验收报告，更新任务计划、需求池、路线图与文档索引，打 `v1.0.0` 标签。

## 3. 验收矩阵

| 编号 | 验收点 | 覆盖方式 |
| --- | --- | --- |
| M5-01 | 正式部署 | 脚本 M5-A：部署脚本 / 模板 / systemd / CI 工作流齐全；`preflight` + `smoke-test` dry-run 通过 |
| M5-02 | 本机一体化 | 脚本 M5-B：`LOCAL_MODE=1` 时 `/local/api/*` 可读、admin 静态托管挂载、默认关闭 |
| M5-03 | 监控与告警 | 脚本 M5-C：`/api/monitoring/status`、`/check`、`/history`、`/alerts`、`/logs` 契约 |
| M5-04 | 备份与恢复 | 脚本 M5-D：SQLite 快照 / 校验 / 恢复演练接口 + 保留策略配置 |
| M5-05 | 安全加固 | 脚本 M5-E：限流 429、内部令牌双令牌、登录防护、安全响应头 |
| M5-06 | 资源预算 | CLI `python -m app.resource_budget check --json`：4G / 15G 红线判定 |
| M5-07 | 运维手册 | 脚本 M5-F：runbook / 诊断脚本存在且 `--help` 可用、章节齐全 |
| M5-08 | 安全审计 | CLI `python -m app.security_audit --root .. --json`：无 critical / high |
| M5-09 | 验收与发布 | 本计划 + `acceptance-m5.md` + 脚本报告 + `v1.0.0` 标签 |

## 4. 交付物

- `vps/scripts/m5_acceptance.py`（可重复执行，支持 `--strict`、`--report-md`、`--report-json`、`--keep`）；
- `docs/planning/acceptance-m5.md`（验收结论与矩阵）；
- `docs/planning/acceptance-m5-report.md` / `.json`（脚本生成的原始报告）；
- `docs/planning/release-v1.0.md`（发布说明：范围、版本、升级 / 回滚、已知限制）；
- 版本号 `1.0.0` 与仓库级标签 `v1.0.0`；
- 文档同步：backlog / task-planning / roadmap / docs README。

## 5. 风险与处理

| 风险 | 处理 |
| --- | --- |
| 八个分支同时改 `config.py` / `schemas.py` / `models.py` / 文档 | 按依赖顺序合并，冲突处保留能力超集，逐次编译 / 跑测试 |
| 无真实 Cloudflare / 域名 / OAuth 凭据 | 验收只覆盖工具链与 dry-run；真实上线列入遗留事项并关联 Q3 |
| 监控 / 备份接口依赖内部令牌 | 验收进程用临时 `INTERNAL_TOKEN`，不接触真实密钥 |
| 安全审计误报阻断发布 | 修正日志关键字匹配（先剥离字符串字面量），补单测 |
| 多任务共用机器 | 所有 pytest / build / test 走 `bacs-heavy`，串行执行，开跑前检查负载与内存 |
