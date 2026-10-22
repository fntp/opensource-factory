# 实施计划 · REQ-202610-0944 资源预算实测验证（4G / 15G 红线；超限优化）

> 需求：REQ-202610-0944（backlog M5-06）｜ 分支：`feat/req-202610-0944-resource-budget`
> 依赖：M5-01 正式部署、M5-02 本机一体化、M5-03 监控告警（资源红线）
> 目标：把 [resource-plan.md](./resource-plan.md) 的 4G 内存 / 15G 磁盘预算变成可重复执行的
> 实测与判定工具，给出实测结论与超限优化建议，并把静态预算约束纳入测试防漂移。

## 1. 现状与缺口

- `resource-plan.md` 只给出预算表与「M5-06 实测核对」计划，没有采集 / 判定工具；
- `deploy/scripts/doctor.sh` 校验运行目录、权限与模型预算，但不统计进程 RSS / 磁盘分项；
- M5-03 监控告警会在运行时按 3.5G / 4G、13G / 15G 阈值告警，但需要一份部署后的实测基线
  来确认预算口径与 systemd `MemoryMax` 静态上限一致；
- 没有统一的「超限时怎么办」清单，容易出现拍脑袋降配。

## 2. 方案总览

```
deploy/scripts/resource-budget.sh
  └─ python -m app.resource_budget check [--home /opt/openfactory] [--json]
       ├─ 内存：systemctl show openfactory-*（MemoryCurrent / MemoryMax）
       │        └─ 无 systemd 时回退 ps RSS 匹配
       ├─ 模型：复用 app.services.model_budget 的峰值驻留估算
       ├─ 磁盘：models / repo / data / logs / backups 分项目录统计
       ├─ 判定：4G / 15G 红线，3.5G / 13G 预警，分项配额
       └─ 结论：PASS / WARN / FAIL + 超限优化建议
```

设计要点：

- **只读、可重复、离线**：不启动 / 停止服务，不修改任何配置；测试不依赖 systemd 与网络；
- **实测与静态上限分开**：实测 RSS 反映当前状态；systemd `MemoryMax` 合计反映最坏情况上限，
  两者都要落在预算内；
- **预算口径与 resource-plan 一致**：应用 2G + AI 2G = 4G；磁盘 15G（模型 4G、仓库依赖 2G、
  数据 2G、日志 1G、备份 3G、余量 3G）；
- **超限只给建议不自动改**：降 Celery 并发、切小模型、清理日志 / 归档 / 备份等动作需要人工确认，
  避免验证工具变成破坏性脚本；
- **CI 防漂移**：`test_resource_budget.py` 校验 systemd 单元上限合计、Redis maxmemory、
  模型峰值与预算表一致，预算被改大时测试直接失败。

## 3. 模块与接口

### 3.1 `vps/app/services/resource_budget.py`（新增，标准库）

| 能力 | 说明 |
| --- | --- |
| `collect_service_usage(units)` | 调 `systemctl show` 读取 ActiveState / MemoryCurrent / MemoryMax；失败返回 unknown |
| `collect_process_memory(ps_text, patterns)` | systemd 不可用时的 RSS 回退口径 |
| `directory_size_bytes(path)` | 递归统计目录实际占用（不跟随符号链接） |
| `collect_disk_usage(home, repo, models_dirs)` | 按预算科目统计 models / repo / data / logs / backups |
| `build_resource_report(...)` | 纯函数：阈值判定、静态上限校验、优化建议 |
| `main(argv)` | `check` 子命令，支持 `--json` / `--no-services` / 自定义预算 |

### 3.2 `vps/app/resource_budget.py`（新增）

CLI 薄入口，转发到 services 模块，保持与 `app.model_budget` 一致的组织方式。

### 3.3 `deploy/scripts/resource-budget.sh`（新增）

部署机入口：优先使用 `vps/.venv/bin/python`，否则回退 `python3`；默认 `--home /opt/openfactory`。

## 4. 阈值与判定

| 检查 | 预警 | 红线 | 超限动作 |
| --- | --- | --- | --- |
| 内存实测（进程 RSS + 模型驻留） | ≥ 3584 MB | > 4096 MB | worker 并发 2→1；缩短 `OLLAMA_KEEP_ALIVE`；切 bge-small |
| 内存静态上限（systemd 合计 + 模型峰值） | — | > 4096 MB | 下调单元 `MemoryMax` 或模型规格 |
| 磁盘合计 | ≥ 13312 MB | > 15360 MB | 清理日志 / 归档 / 备份，SQLite VACUUM |
| 磁盘分项 | 超各自配额 | — | 按科目清理（模型 / 依赖 / 数据 / 日志 / 备份） |

退出码：`0` = PASS / WARN；`1` = FAIL（任一红线被突破）；`--strict` 时 WARN 也返回 1。

## 5. 文档

- 新增 `docs/guides/resource-budget-verification.md`：实测方法、2026-10-22 本机基线、
  超限优化清单、验收记录；
- 更新 `docs/planning/resource-plan.md` §6：挂接工具与实测结论；
- 更新 `docs/requirements/backlog.md` M5-06 状态、`docs/planning/task-planning.md` 迭代记录；
- 更新 `docs/README.md`、`deploy/README.md` 入口说明。

## 6. 测试与验收

| 层 | 用例 |
| --- | --- |
| vps | `tests/test_resource_budget.py`：systemd / ps / 目录统计解析、阈值边界、分项超限、静态上限、CLI JSON 与退出码 |
| deploy | `test_deploy_assets.py` 扩展：脚本 `bash -n` / `--help`、systemd 上限合计 ≤ 2G、Redis maxmemory 256MB |
| 实测 | 本机执行 `deploy/scripts/resource-budget.sh --json`，记录内存 / 磁盘分项与结论 |

验收标准：

1. 一条命令输出内存 / 磁盘实测值、预算占比、PASS/WARN/FAIL 结论；
2. 4G / 15G 红线与 3.5G / 13G 预警可配置且有边界测试；
3. systemd 静态上限合计 ≤ 2G、模型峰值 ≤ 2G、磁盘科目合计 = 15G 由测试锁定；
4. 超限时输出可执行的优化建议（不自动改配置）；
5. `vps` 全量 pytest 通过，部署脚本 `bash -n` 通过。

## 7. 风险与后续

- 本机当前只运行 api / redis，worker / beat 与 Ollama 未启用，实测为「部分负载基线」；
  完整上线后需按本文档复跑并更新基线；
- systemd `MemoryCurrent` 在容器 / 非 cgroup 环境可能不可读，已提供 ps 回退与 unknown 状态；
- M5-03 监控告警与本文档阈值需保持一致（3.5G / 4G、13G / 15G），集成时以 resource-plan 为准。
