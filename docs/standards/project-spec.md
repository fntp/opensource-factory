# 项目规范 · Project Specification

> 规范编号：STD-01 ｜ 适用范围：整个仓库 ｜ 维护人：fntp

## 1. 项目定位

「开源项目工厂 / OpenFactory」是**个人开源资产管理与智能推荐系统**，解决三个核心痛点：

- 开源项目散落各处，难以按业务线二次复用 → 统一收录与多维分类；
- 无法定向发现适合自己的新项目 → 全网热榜 + 语义推荐；
- 收藏即遗忘 → 每日定向 Push。

## 2. 架构原则

1. **边缘轻量、算力下沉**：控制面与元数据放在 Cloudflare（0 成本、全球加速），重算力（爬虫、Embedding、LLM）放在本地 VPS；
2. **边缘不跑重任务**：Workers 只做鉴权、调度与元数据读写；一切耗时任务通过内部 API 交给 VPS 节点异步执行；
3. **本地优先、隐私安全**：LLM 与向量化优先使用本地模型（Ollama / BGE-M3），云端 API 仅作可选降级；
4. **优雅降级**：外部依赖（LLM、模型、爬虫目标站点）不可用时系统必须可用（降级返回，不抛错阻塞）。

## 3. 目录结构与职责

```
admin/   # 前端控制台：仅做展示与交互，不存放任何密钥
edge/    # 边缘 API：鉴权、调度、D1 读写、Vectorize 检索
vps/     # 算力节点：爬虫、清洗、摘要、向量化、推荐、推送
docs/    # 文档与数据资产（唯一来源）
.github/ # CI 工作流
```

- 新增子项目需在本文件与 `docs/architecture/overview.md` 登记；
- 子项目内部结构遵循各自生态惯例（见 [code-constraints.md](./code-constraints.md)）。

## 4. 分支与版本

| 项 | 约定 |
| --- | --- |
| 主分支 | `main`，受保护，禁止直接提交 |
| 需求分支 | `feat/req-<需求编号>-<简述>`，如 `feat/req-202610-0454-init` |
| 修复分支 | `fix/<简述>` |
| 版本 | 子项目独立版本号（SemVer）；仓库级以里程碑标签记录 |
| 合并方式 | Squash 或常规合并均可，必须通过 CI |

## 5. 依赖管理

- **admin / edge**：npm，提交 `package-lock.json`；新增依赖需说明理由；
- **vps**：pip + `requirements.txt`（轻量）与 `requirements-ml.txt`（重型可选）；
- 依赖升级单独提交，不与功能混提。

## 6. 配置与环境变量

- 所有配置项必须提供 `.env.example`（占位符，可提交）；
- 真实值只存在于：本地 `.env`（git 忽略）、平台密钥托管（Cloudflare secrets / GitHub secrets）；
- 命名：`UPPER_SNAKE_CASE`，前端可见变量必须以 `VITE_` 前缀且**不得包含敏感信息**。

## 7. 安全红线

1. token / 密钥 / 口令：不提交、不打印、不写入前端产物；
2. 对外接口（edge）一律带鉴权；内部接口（edge→vps）使用 `X-Internal-Token`；
3. 用户数据仅用于本系统功能，不做任何外发；
4. 发现泄漏：立即轮换并在 `docs/requirements/open-questions.md` 记录处置。

## 8. 文档与沟通

- 文档集中存放于 `docs/`（本文件所在体系）；
- 需求不确定点：记入 `docs/requirements/open-questions.md`，给出 2-3 个选项与默认建议，等待确认后更新需求；
- 每个需求完成后在 `docs/planning/task-planning.md` 更新状态。
