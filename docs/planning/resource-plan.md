# 资源规划 · Resource Plan

> 文档编号：PL-03 ｜ 来源需求：REQ-202610-0462 ｜ 维护人：fntp ｜ 更新方式：预算 / 部署形态变化时更新

## 1. 总预算

按维护者口径：本机将**专门用于部署与运行本项目**；项目预算如下（其余容量不作占用假设）：

| 资源 | 预算 | 分配 |
| --- | --- | --- |
| 运行内存 | **约 4G** | 前后端应用 2G + AI 深度学习推理 2G（见 §2 / §3） |
| 磁盘空间 | **约 15G** | 模型 / 依赖 / 数据 / 日志 / 备份（见 §4） |

> 现状参考（2026-10-13 实测）：本机内存 7.6G / 磁盘 75G（可用 58G）；本表为项目占用上限，部署与压测时以本表为准。

## 2. 应用侧预算（2G）

| 组件 | 典型占用（RSS） | 策略 |
| --- | --- | --- |
| FastAPI（uvicorn，单 worker） | 120–200 MB | 生产单进程；静态资源交给 Caddy |
| Celery worker（并发 ≤ 2） | 250–350 MB | AI 相关任务串行化（见 §3） |
| Celery beat（定时调度） | 60–100 MB | 与 worker 分进程 |
| Redis（broker / 缓存） | 150–300 MB | `maxmemory 256MB`，监控防溢出 |
| Caddy（静态托管 / 反代，可选） | 30–60 MB | 托管 admin 构建产物 |
| 峰值余量 | ~900 MB | 构建、临时任务、监控缓冲 |
| **合计** | **≤ 2.0 GB** | 超限时降并发 / 拆任务 |

## 3. AI 推理侧预算（2G）

**约束**：同一时刻仅加载 1 个模型（任务串行 + `keep_alive` 控制），模型总驻留 ≤ 2G。

| 用途 | 候选模型 | 驻留内存（估） | 磁盘（估） | 说明 |
| --- | --- | --- | --- | --- |
| Embedding（首选） | bge-m3（q8 / ONNX int8 量化） | ~0.8–1.2 GB | ~1.2 GB | 1024 维；fp16 约 2.3G 超预算，需量化 |
| Embedding（降级） | bge-small-zh-v1.5 | ~0.3 GB | ~0.1 GB | 超限时切换 |
| LLM 摘要（首选） | qwen2.5:1.5b-instruct（q4_K_M） | ~1.3 GB | ~1.0 GB | 中文摘要默认 |
| LLM 备选 | deepseek-r1:1.5b（q4） | ~1.4 GB | ~1.1 GB | 推理型，较慢 |
| 超预算（不默认） | qwen2.5:7b / deepseek-r1:7b（q4） | ~4.7 GB | ~4.7 GB | ❌ 超 2G，仅按需人工启用 |

- **M3-01 选型结论（2026-10-22）**：默认切换为 `BAAI/bge-m3`（int8，约 1.1G）+ `qwen2.5:1.5b-instruct-q4_K_M`（约 1.3G）；旧默认 `qwen2.5:7b`（约 4.7G）不再默认启用；
- **预算校验**：`cd vps && .venv/bin/python -m app.model_budget check`（`--probe` 读取 Ollama `/api/ps`）；`deploy/scripts/doctor.sh` 已纳入同一检查；
- **调度**：Embedding 批量任务与摘要任务分队列串行；Ollama `keep_alive` 缩短（如 2m），空闲即卸载；
- **降级链**：模型不可用 / 超预算 → hash 兜底向量、截断摘要（沿用现有降级路径，M3-09 验证）。

## 4. 磁盘预算（15G）

| 项目 | 配额 | 说明 / 清理策略 |
| --- | --- | --- |
| 模型文件 | 4.0 GB | bge-m3 ~1.2G + LLM ~1.1G + 备选 / 升级余量 |
| 仓库与依赖 | 2.0 GB | 源码 + admin/edge node_modules + vps venv（轻量，不含 torch） |
| 数据（SQLite 镜像 / 缓存） | 2.0 GB | 定期 VACUUM / 归档；增长监控 |
| 日志 | 1.0 GB | 轮转保留 14 天 |
| 备份 | 3.0 GB | D1 导出 + SQLite 快照，保留最近 7 份；M5-04 已按 `BACKUP_MAX_TOTAL_MB=3072` 强制清理 |
| 余量 | 3.0 GB | 构建 / 临时文件 / 系统缓冲 |
| **合计** | **15.0 GB** | 超限告警（M5-03） |

## 5. 部署与保密

### 5.1 部署形态

- **目标**：项目部署并运行于本机（唯一运行环境）；
- **进程清单**（本机）：`vps-api`、`vps-worker`、`vps-beat`、`redis`、`ollama`、`caddy`（静态托管，可选）；
- **运行目录**：`/opt/openfactory/`（`.env`、`etc/redis.conf`、`data/`、`logs/`、`backups/`、`run/`；仅本机、不进仓库），基线见 [deployment-baseline.md](../guides/deployment-baseline.md)；
- **云侧组件**：Cloudflare Pages / Workers / D1 / Vectorize（免费额度内）不占本机资源；是否完全本机化见 [Q9](../requirements/open-questions.md)。

### 5.2 配置文件分级（公开 / 私有）

| 级别 | 位置 | 内容 |
| --- | --- | --- |
| 公开（可入库） | 仓库 | `.env.example`、`wrangler.toml`（占位）、CI 配置 |
| 私有（仅本机） | `/opt/openfactory/.env` 等（权限 600/700） | 真实密钥 / token / 账号配置 |

- 红线：任何 token / 密钥不得入库、不得回显（见 code-constraints、AGENTS.md §2）；
- `.env` 已被 `.gitignore` 忽略；新增配置项必须同步 `.env.example`。

### 5.3 保密要求

- 项目开源，但**部署实例不对外分享**；仓库不含任何个人数据；
- 个人数据（收藏、画像、推送记录）仅存于本机（与可选的 Cloudflare 元数据，见 Q9）；
- 数据外发仅限功能必需（如 Bark / Telegram 推送），可关闭。

## 6. 预算验证与监控

- **验证计划**：M5-06 按本表实测核对（进程 RSS / 磁盘占用 / 模型驻留），超限即优化（降并发、换更小模型、清理策略）；
- **日常监控**：M5-03 资源红线告警（内存 > 3.5G、磁盘 > 13G 预警）；
- **关联问题**：Q3（Cloudflare 资源信息）、Q9（部署口径与边缘去留）。
