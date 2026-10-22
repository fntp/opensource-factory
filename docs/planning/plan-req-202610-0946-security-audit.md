# 实施计划 · REQ-202610-0946 安全审计（依赖漏洞扫描 / 配置检查 / 隐私边界复核）

> 需求：REQ-202610-0946（backlog M5-08）｜ 分支：`feat/req-202610-0946-security-audit`
> 依赖：M5-01（REQ-202610-0939 正式部署工具链）｜ 基线：`feat/req-202610-0943-security-hardening` @ `65f6cc2`

## 1. 现状与缺口

- 三端依赖分散在 `admin/package-lock.json`、`edge/package-lock.json`、`vps/requirements*.txt`，没有统一的依赖漏洞扫描入口，CI 也不检查依赖安全；
- 配置项分布在 `vps/app/config.py`、`deploy/env/*.example`、`edge/wrangler.toml` 与生产模板中，CORS、限流、内部令牌、Cookie 等安全开关缺少自动校验，容易在部署时回退到开发默认值；
- 隐私数据边界没有清单：`users.email/name/avatar_url`、`sessions`、`login_attempts.ip_hash`、`recommendations.user_id` 等字段的采集目的、日志暴露面与保留期未集中说明；
- 代码中缺少防回归的安全基线检查（密钥误提交、Cookie 标记、安全响应头、日志打印敏感字段）；
- M5-05 已交付限流与令牌轮换，但审计仍靠人工，无法在每次提交 / 发布前复跑。

## 2. 方案总览

新增一个**只读、离线优先**的安全审计工具，三端共用：

```
vps/app/security_audit.py        审计核心 + CLI（仅标准库，无第三方依赖）
deploy/scripts/security-audit.sh 部署机 / CI 入口（自动定位仓库、venv、转发参数）
.github/workflows/ci.yml         新增 security job：静态审计 + npm audit + pip-audit
docs/guides/security-audit.md    审计口径、基线结果、整改记录、复扫与例外流程
```

审计维度：

| 维度 | 检查 | 严重度 |
| --- | --- | --- |
| 依赖漏洞 | `npm audit`（admin / edge，可 `--online`）、`pip-audit`（vps venv，可 `--online`） | critical / high |
| 依赖完整性 | lockfile 版本、`integrity` 字段、`http://` 源、Python 依赖固定版本 | medium |
| 密钥泄露 | GitHub PAT、云厂商 Key、私钥块、Slack Token、疑似真实 API Key；`.env` 是否被跟踪 | high |
| 配置基线 | 生产 CORS 禁止 `*`、限流开启、内部令牌长度、占位符未替换、调试开关 | high / medium |
| 会话与响应头 | Cookie `HttpOnly` / `SameSite` / `Secure`、edge `secureHeaders` | high |
| 隐私边界 | PII 字段清单、日志敏感字段扫描、第三方出网点清单、保留期缺口 | medium / low |

输出：

- 文本报告（默认，按严重度分组，含 `file:line` 证据与整改建议）；
- `--json` 机器可读报告（CI / 平台归档）；
- `--strict`：存在 high / critical 时退出码 1；默认仅 critical 退出码 1；
- `--online`：额外执行真实依赖漏洞扫描（npm audit / pip-audit），默认关闭以保证离线与测试稳定。

## 3. 检查实现要点

1. **密钥扫描**：按文件类型白名单扫描源码 / 配置 / 文档，跳过 `.git`、`node_modules`、`.venv`、构建产物与测试夹具；占位符（`REPLACE_WITH_`、`<...>`、`example`、`changeme`、`${...}`、含 `*` 的脱敏串）不报。
2. **配置检查**：解析 `deploy/env/openfactory.env.example`、`deploy/env/deploy.env.example`、`vps/.env.example`、`edge/wrangler.toml`、`deploy/templates/wrangler.production.toml.tmpl`；若指定 `--runtime-env` 或环境变量 `OPENFACTORY_HOME`，额外检查真实运行 `.env`（只读，不输出值）。
3. **Cookie / 响应头**：静态断言 `edge/src/auth.ts` 的 `buildSetCookie` 含 `HttpOnly`、`SameSite`、`Secure` 分支；`edge/src/index.ts` 使用 `secureHeaders` 中间件。
4. **隐私边界**：从 D1 迁移与 VPS 模型中提取 PII 字段，生成清单；扫描日志调用中是否直接拼接 `email` / `token` / `cookie` / `authorization` / 原始 IP；列出第三方出网域名（GitHub、DeepSeek、Ollama、Cloudflare）。
5. **依赖漏洞**：`--online` 时运行 `npm audit --package-lock-only --json` 与 `pip-audit --path <venv site-packages> --format json`，解析 `high` / `critical`；工具缺失时降级为 `info` 并提示安装方式，不阻塞离线审计。

## 4. 代码与文档改动

- 新增 `vps/app/security_audit.py`：审计核心、检查函数、报告渲染、CLI；
- 新增 `vps/tests/test_security_audit.py`：用临时夹具覆盖密钥、CORS、Cookie、锁文件、隐私日志、JSON / 退出码；
- 新增 `deploy/scripts/security-audit.sh`：一键入口，默认离线，`--online` 透传；
- 更新 `vps/tests/test_deploy_assets.py`：纳管新脚本的 `bash -n` / `--help`；
- 更新 `.github/workflows/ci.yml`：新增 security job（静态审计 `--strict` + npm audit + pip-audit）；
- 新增 `docs/guides/security-audit.md`：审计范围、运行方式、2026-10-22 基线结果、发现与整改、隐私边界表、例外与复扫；
- 更新 `docs/README.md`、`docs/planning/roadmap.md`、`docs/planning/task-planning.md`、`docs/requirements/backlog.md`（如适用）与三端 README。

## 5. 测试与验收

| 层 | 用例 |
| --- | --- |
| 单元 | 密钥模式命中 / 占位符不误报；CORS `*` 判定；Cookie 标记缺失判定；lockfile 完整性；隐私日志扫描；报告 JSON 结构与退出码 |
| 集成 | `python -m app.security_audit --root <repo> --json` 在当前仓库运行，无 high / critical；`--strict` 退出码 0 |
| 部署资产 | `bash -n deploy/scripts/security-audit.sh`；`--help` 冒烟 |
| 三端回归 | vps `pytest -q`；edge `npm run typecheck` + 安全路由测试；admin `npm run lint && npm run build && npm run test` |

验收标准：

1. 审计工具能离线运行，输出文本 / JSON，`--strict` 对 high / critical 返回非零；
2. 当前分支基线审计无 high / critical，medium / low 项有明确整改建议；
3. 密钥扫描不误报模板占位符，能命中测试夹具中的真实格式令牌；
4. CI 新增 security job 可在无 Cloudflare / 本机凭据的情况下通过（在线依赖扫描失败时给出可诊断信息）；
5. 文档给出可复跑的审计命令、基线结果与遗留风险。

## 6. 风险与后续

- `npm audit` / `pip-audit` 依赖外网与漏洞库时效，CI 中作为补充而非唯一门禁；离线静态检查保证基本回归；
- Python 依赖当前使用 `>=` 下限，完全锁定版本会牵动部署与模型依赖，本需求先以 `medium` 记录，后续可引入 `requirements.lock`；
- 隐私数据删除 / 导出能力属于 M9-06（数据保留与隐私策略落地），本需求只做边界复核与清单，不实现用户数据删除接口；
- 审计工具为只读，不修改运行配置、不启动 / 停止服务。
