# 贡献指南 · Contributing

感谢参与「开源项目工厂 / OpenFactory」。本文档描述本地开发、提交与合并流程，适用于人类贡献者与 AI Agent（另见 [AGENTS.md](./AGENTS.md)）。

## 1. 分支模型

- `main` 为受保护主分支，**禁止直接提交**；
- 功能开发一律从最新 `main` 切出需求分支：

```bash
git checkout main && git pull
git checkout -b feat/req-<需求编号>-<简述>   # 例如 feat/req-202610-0454-init
```

- 分支命名：`feat/` 新功能 · `fix/` 修复 · `docs/` 文档 · `chore/` 杂项；
- 不强制推送（`--force`），不删除他人分支。

## 2. 提交信息（Conventional Commits）

```
<type>(<scope>): <中文描述>

[可选的详细说明]

Co-Authored-By: Claude Code <noreply@anthropic.com>
```

- `type`：`feat` / `fix` / `docs` / `style` / `refactor` / `test` / `chore` / `ci`
- `scope`：`admin` / `edge` / `vps` / `docs` / `repo`
- 描述使用中文，一句话说明「做了什么」。

示例：`feat(admin): 新增仓库列表与分类标签页面`

## 3. 提交前检查（必须全绿）

| 子项目 | 命令 |
| --- | --- |
| admin | `npm run lint && npm run build && npm run test` |
| edge | `npm run typecheck` |
| vps | `.venv/bin/pytest -q` |

## 4. 文档义务

- 任何行为变更必须同步更新 `docs/` 下对应文档（详见 [docs/standards/project-spec.md](./docs/standards/project-spec.md)）；
- 新增配置项必须补充到对应的 `.env.example`；
- 需求类变更记录到 `docs/requirements/`。

## 5. 安全红线

- **任何 token、密钥、口令都不得提交到仓库**，也不得回显到日志；
- 本地密钥只放在 `.env`（已被 .gitignore 忽略）或 Cloudflare secrets；
- 发现泄漏立即轮换密钥并在 issue 中说明。

## 6. Pull Request

- PR 目标分支为 `main`，描述中包含：变更摘要 / 测试结果 / 关联需求编号；
- PR 描述末尾附：

```
🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

- 至少 1 人 review 通过后合并（个人项目可由维护者自行合并）。
