# Agent 维护文档 · Agent Maintenance Guide

> 文档编号：GD-01 ｜ 适用对象：Claude Code 等 AI Agent ｜ 维护人：fntp

本文档说明 AI Agent 在本仓库执行任务时的标准流程。配合根目录 [AGENTS.md](../../AGENTS.md) 使用。

## 1. 环境信息

| 项 | 值 |
| --- | --- |
| Node.js | 22.x（admin / edge） |
| Python | 3.12（vps，使用 `.venv`） |
| 包管理器 | npm（提交 lockfile） |
| 测试框架 | Vitest（浏览器模式，headless）/ pytest |
| 工作目录 | 仓库根（`/opt/refs/opensource-factory` 或对应检出目录） |

## 2. 标准执行流程

```
1) 读取规范：AGENTS.md → CLAUDE.md → docs/standards/** → 任务相关文档
2) 检查现状：git status / git branch（保护本地修改；不在 main 上开发）
3) 切需求分支：git checkout -b feat/req-<编号>-<简述>（已存在则复用）
4) 实施：基于需求文档 + 技术方案 + 项目现状；代码与文档冲突时以代码为准
5) 验证：运行对应子项目检查（见第 3 节），全绿
6) 提交：Conventional Commits + 中文；附 Co-Authored-By
7) 推送：git push origin <分支>（不强推）
8) 回报：修改摘要 / 测试结果 / 提交哈希 / 待人工处理问题
```

## 3. 验证命令速查

```bash
# admin
cd admin && npm run lint && npm run build && npm run test

# edge
cd edge && npm run typecheck

# vps
cd vps && .venv/bin/pytest -q
```

## 4. 常见坑与规避

| 问题 | 说明 |
| --- | --- |
| `routeTree.gen.ts` 过期 | 增删路由后必须重新构建（`npx vite build`）以重新生成 |
| Vitest 浏览器模式 | 服务器无图形界面，配置已设 `headless: true`；新机器需 `npx playwright install chromium` + `--with-deps` |
| npm install 首次较慢 | 属正常；CI 使用 `npm ci` |
| D1 迁移 | `wrangler d1 migrations apply <db> --local`；`wrangler.toml` 中 `database_id` 是占位符，需人工替换 |
| 重型 ML 依赖 | vps 默认不装 torch；`embedding.py` 有确定性哈希兜底，测试不依赖模型 |
| 密钥 | 只从环境变量 / secrets 读取；**任何情况下不得回显到日志或提交** |

## 5. 文档同步义务

改动行为 / 结构 / 接口 / 数据模型时，同一提交内更新对应文档（对照表见 [AGENTS.md](../../AGENTS.md) §5）。

## 6. 与平台（BACS）的交互

- 任务完成后按平台要求执行回调（回调命令由任务下发，不在仓库中保存）；
- 回调内容必须真实：修改摘要、测试结果、提交哈希、仍需人工处理的问题；
- 推送失败或凭据不可用时：如实上报（status=error + 原因），不得谎报完成；
- **平台 token / 凭据不得写入仓库任何文件**。
