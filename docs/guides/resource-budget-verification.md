# 资源预算实测验证 · Resource Budget Verification

> 文档编号：GD-05 ｜ 对应需求：REQ-202610-0944（backlog M5-06）｜ 维护人：fntp
> 适用版本：v0.1.x ｜ 更新方式：部署形态 / 模型 / 数据量变化后复测并更新基线

本文档把 [resource-plan.md](../planning/resource-plan.md) 的 **4G 内存 / 15G 磁盘**预算
变成可重复执行的实测流程：一条命令采集进程 RSS、模型峰值、磁盘分项并给出 PASS / WARN / FAIL
结论；超限时按第 6 节优化后复测。

## 1. 快速开始

```bash
# 部署机默认口径（/opt/openfactory，代码目录自动识别）
deploy/scripts/resource-budget.sh

# JSON（供监控 / 验收脚本消费）
deploy/scripts/resource-budget.sh --json

# 只读采集，不依赖 systemd（容器 / CI）
deploy/scripts/resource-budget.sh --no-services

# 预警也视为失败（发布门禁）
deploy/scripts/resource-budget.sh --strict
```

等价的 Python 入口：

```bash
cd vps
python -m app.resource_budget check --home /opt/openfactory --repo /opt/workspace/opensource-factory
```

退出码：`0` = PASS / WARN；`1` = FAIL（任一红线被突破）；`--strict` 时 WARN / UNKNOWN 也返回 `1`。
工具**只读**，不会启动 / 停止服务，也不会删除文件。

## 2. 判定口径

| 检查 | 数据来源 | 预警 | 红线 |
| --- | --- | --- | --- |
| 内存实测 | `systemctl show openfactory-*.service` 的 `MemoryCurrent`；不可用时回退 `ps` RSS | ≥ 3584 MB | > 4096 MB |
| 内存峰值 | 实测进程 + 模型峰值驻留（`app.model_budget` 选型表） | ≥ 3584 MB | > 4096 MB |
| 内存静态上限 | `deploy/systemd/*.service` 的 `MemoryMax` 合计 + 模型峰值 | — | > 4096 MB |
| 模型预算 | 当前 `EMBEDDING_MODEL` / `OLLAMA_MODEL` 的峰值驻留 | — | > 2048 MB |
| 磁盘合计 | models / repo / data / logs / backups 分项之和 | ≥ 13312 MB | > 15360 MB |
| 磁盘分项 | 各科目实际占用 vs resource-plan §4 配额 | 超配额 | — |

预算科目：模型 4G、仓库与依赖 2G、数据 2G、日志 1G、备份 3G、余量 3G。
模型目录默认探测 `OLLAMA_MODELS`、`~/.ollama/models`、`~/.cache/huggingface/hub`；
可用 `--models-dir` 重复指定。

## 3. 本机基线（2026-10-22 实测）

执行环境：Ubuntu 24.04 / 8 核 / 15G 内存；运行目录 `/opt/openfactory`；
代码目录 `/opt/workspace/opensource-factory`。

| 项目 | 实测 | 预算 | 占比 | 结论 |
| --- | --- | --- | --- | --- |
| openfactory-api.service | 56.6 MB | 384 MB | 14.7% | OK |
| openfactory-worker.service | 未运行（0 MB） | 768 MB | — | OK |
| openfactory-beat.service | 未运行（0 MB） | 192 MB | — | OK |
| openfactory-redis.service | 2.6 MB | 320 MB | 0.8% | OK |
| 模型峰值（选型估算） | 1300 MB | 2048 MB | 63.5% | OK |
| **内存合计（实测 + 模型峰值）** | **1359.2 MB** | **4096 MB** | **33.2%** | **PASS** |
| 内存静态上限（systemd 1664 MB + 模型 1300 MB） | 2964 MB | 4096 MB | 72.4% | PASS |
| 模型 / 仓库 / 数据 / 日志 / 备份 | 7.4 / 98.7 / 0.1 / 0.0 / 0.0 MB | 4G / 2G / 2G / 1G / 3G | < 5% | OK |
| **磁盘合计** | **106.2 MB** | **15360 MB** | **0.7%** | **PASS** |

结论：**PASS**。当前只运行 API / Redis，worker / beat 与 Ollama 尚未启用；模型峰值按
`app.model_budget` 选型表（bge-m3 int8 ≈ 1100 MB、qwen2.5:1.5b q4 ≈ 1300 MB，取峰值）
估算。完整启用后需复跑本命令并更新本节基线。

## 4. 本次超限优化（真实发现）

首次实测发现运行目录 `/opt/openfactory/.env` 仍是部署基线初版的 `OLLAMA_MODEL=qwen2.5:7b`：

- 模型峰值 **4700 MB > 2048 MB**，内存峰值 **4719 MB / 4096 MB（115.2%）**，判定 FAIL；
- 原因：运行配置由旧版 `bootstrap-runtime.sh` 生成，之后模板已切到 ≤2B 量化模型，
  但 bootstrap 对已存在的 `.env` 默认不覆盖，导致「模板正确、运行配置漂移」。

优化动作（2026-10-22，运行目录，未入库）：

1. `OLLAMA_MODEL=qwen2.5:1.5b-instruct-q4_K_M`（峰值 1300 MB）；
2. `OLLAMA_KEEP_ALIVE=2m`（任务结束及时卸载，释放 2G 推理预算）；
3. `EMBEDDING_QUANTIZATION=int8`（bge-m3 fp16 约 2.3G 超预算）；
4. `MODEL_BUDGET_MB=2048`（与 resource-plan §3 对齐）；
5. `systemctl restart openfactory-api` 使配置生效。

复测结果：内存峰值 1359.2 / 4096 MB、磁盘 106.2 / 15360 MB，**PASS**。

> 运行配置属于 `/opt/openfactory` 私有资产，不提交仓库；模板与默认值已在
> `vps/.env.example` / `deploy/env/openfactory.env.example` 中保持一致。

## 5. 验收清单

- [x] `deploy/scripts/resource-budget.sh` 一条命令输出内存 / 磁盘实测与结论；
- [x] 4G / 15G 红线、3.5G / 13G 预警可配置，边界有单测覆盖；
- [x] systemd `MemoryMax` 合计 1664 MB ≤ 应用 2G 预算，由测试锁定；
- [x] 模型峰值 1300 MB ≤ AI 2G 预算，由 `test_model_budget.py` 锁定；
- [x] 磁盘科目合计 12288 MB + 余量 3072 MB = 15360 MB，由测试锁定；
- [x] 超限时输出可执行的优化建议（不自动改配置）；
- [x] 本机实测 PASS，基线记录于第 3 节。

## 6. 超限优化手册

| 超限项 | 优先动作 | 仍超限时 |
| --- | --- | --- |
| 内存（应用） | `openfactory-worker` 并发 2 → 1；确认 `OLLAMA_KEEP_ALIVE=2m` | 拆分队列 / 降低 `SUMMARY_MAX_PER_RUN` / 减少 worker 数 |
| 内存（模型） | 切 `BAAI/bge-small-zh-v1.5`（≈300 MB）；确认 `EMBEDDING_QUANTIZATION=int8` | 停用非必要 AI 任务，摘要走云端降级 |
| 磁盘（模型） | 删除未使用模型缓存，仅保留 bge-m3 int8 与 ≤2B LLM | 迁移 `OLLAMA_MODELS` 到独立磁盘 |
| 磁盘（仓库） | 清理 `node_modules` / `.venv` 缓存与构建产物 | 重建虚拟环境，依赖按需安装 |
| 磁盘（数据） | SQLite `VACUUM`；清理过期热榜归档（`TRENDING_ARCHIVE_KEEP_DAYS`） | 缩短保留窗口 / 归档到外部存储 |
| 磁盘（日志） | 清理 14 天前日志；确认 API `RotatingFileHandler` 生效 | 降低日志级别 / 缩短保留天数 |
| 磁盘（备份） | 按保留策略删除旧备份（最近 7 份） | 备份转存外部存储 |

## 7. 与监控告警的关系

M5-03 监控在运行时按 3.5G / 4G、13G / 15G 阈值持续告警；本文档提供**部署后基线**
与**一次性验收口径**，两者阈值必须保持一致（以 [resource-plan.md](../planning/resource-plan.md) 为准）。
监控告警负责「持续发现问题」，本工具负责「验收时证明预算成立、超限时给出优化路径」。
