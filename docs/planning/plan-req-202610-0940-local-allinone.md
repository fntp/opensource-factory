# 实施计划 · REQ-202610-0940 本机一体化部署模式评估与落地（离线自托管；Q9）

> 需求：REQ-202610-0940（backlog M5-02）｜ 分支：`feat/req-202610-0940-local-allinone`
> 依赖：Q9（部署口径）；M1~M4（功能与部署基线）
> 目标：评估「本机一体化（选项 B）」并落地一条可离线自托管的运行路径：单进程同时提供
> admin 静态页面与 edge 兼容的只读 API，数据只读本机 SQLite，不依赖 Cloudflare。

## 1. 现状与缺口

- 现行架构（Q9 选项 A，混合）：admin 在 Pages、edge 在 Workers、数据主库在 D1；
  本机 VPS 只承担同步 / 抓取 / 推理 / 推送，断网或没有 Cloudflare 凭据时前端不可用；
- `deploy/` 已有运行目录、Redis、systemd 与 env 模板（REQ-202610-0893），但只覆盖 VPS 节点；
- VPS 已有 SQLite 镜像表（`my_repositories` / `trending_repositories` / `categories` /
  `recommendations`），但只有内部任务 API，没有面向前端的 edge 兼容 API；
- admin 构建产物没有本机托管入口，`VITE_API_BASE_URL` 为空时会进入演示模式。

## 2. 方案总览

```
┌──────────────────── 本机单进程（openfactory-api）────────────────────┐
│  GET /                      admin/dist 静态资源（SPA 回退）           │
│  GET /local/api/*           edge 兼容只读 API（单用户、本机信任）      │
│  GET /api/*                 既有 VPS 任务 / 检索 API（内部令牌）       │
│  GET /healthz               健康检查                                   │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ SQLAlchemy
                     /opt/openfactory/data/*.db（SQLite）
```

- 开关：`LOCAL_MODE=true` 时挂载 `/local` API 与 admin 静态托管；默认关闭，混合架构不受影响；
- admin 构建：`VITE_API_BASE_URL=/local`、`VITE_DEMO_MODE=false`，同源请求，无需 CORS / Cookie；
- 单用户：`LOCAL_USER_ID` / `LOCAL_USER_LOGIN` / `LOCAL_USER_NAME` 配置本机身份，
  `/local/api/auth/me` 直接返回，不做 GitHub OAuth；
- 只读边界：首版本地 API 仅提供仪表盘、仓库、热榜、推荐、分类的读接口；
  写操作仍走 VPS 任务 / 后续迭代，避免在单用户模式下引入第二套鉴权。

## 3. 交付物

### 3.1 代码

| 文件 | 内容 |
| --- | --- |
| `vps/app/api/local.py` | edge 兼容只读 API：auth/me、repos、trending（列表 / 日期 / 语言 / 详情）、recommendations（列表 / 统计）、categories、dashboard/stats、local/status |
| `vps/app/local_ui.py` | admin 静态托管与 SPA 回退（路径穿越防护、缺失构建提示） |
| `vps/app/config.py` | `LOCAL_MODE` / `LOCAL_USER_*` / `LOCAL_ADMIN_DIR` |
| `vps/app/main.py` | 按 `LOCAL_MODE` 挂载 `/local` 路由与静态站点 |
| `vps/tests/test_local_mode.py` | 端点契约、筛选、静态托管、开关关闭 404 |

### 3.2 部署

| 文件 | 内容 |
| --- | --- |
| `deploy/scripts/local-allinone.sh` | `build`（admin 构建并复制到运行目录）/ `enable` / `disable` / `status` / `verify` |
| `deploy/env/openfactory.env.example`、`vps/.env.example` | 新增 `LOCAL_*` 配置说明 |
| `vps/app/runtime.py` | `REQUIRED_ENV_KEYS` 同步新增字段 |

### 3.3 文档

- `docs/guides/local-allinone-deployment.md`：评估矩阵（A/B/C）、资源与安全边界、部署 / 升级 / 回滚 / 离线验收；
- `docs/architecture/overview.md`：新增本机一体化拓扑与接口边界；
- `docs/requirements/open-questions.md`：Q9 更新为「B 已可落地，默认仍 A，待维护者切换」；
- `docs/requirements/backlog.md` / `docs/planning/roadmap.md` / `docs/planning/task-planning.md` / `docs/README.md`：状态与索引同步。

## 4. 测试与验收

| 层 | 用例 |
| --- | --- |
| 本地 API | TestClient 覆盖核心读接口的 JSON 契约、`q` / `categoryId` / `date` / `limit` 过滤、空库返回 |
| 开关 | `LOCAL_MODE=false` 时 `/local/api/*` 返回 404；`true` 时 `/local/api/local/status` 正常 |
| 静态托管 | 临时目录放 `index.html` + 资源文件，校验根路径、资源与 SPA 回退；缺失目录返回 503 提示 |
| 部署资产 | `test_deploy_assets.py` 校验两份 env 模板覆盖全部 `Settings` 字段；脚本 `bash -n` |
| 回归 | `vps/.venv/bin/pytest -q` 全绿 |

验收标准：

1. 断网、无 Cloudflare 凭据时，`http://127.0.0.1:8000/` 可打开 admin，5 个页面读取本机 SQLite 数据；
2. `LOCAL_MODE` 默认关闭，混合部署行为不变；
3. 一条命令完成 admin 构建 + 运行目录部署，`local-allinone.sh verify` 全绿；
4. 评估文档给出 A/B 对比、资源占用、迁移与回滚步骤。

## 5. 风险与边界

- **只读首版**：本地模式不提供收藏 / 分类编辑等写接口；需要写入时仍连 edge 或后续补本地写路径；
- **数据来源**：本地 API 读 VPS SQLite 镜像，D1 主库不会自动回流；离线模式以 VPS 任务抓取 / 同步为准；
- **单用户信任模型**：仅监听 `127.0.0.1`，不要直接暴露公网；如需反代，必须叠加认证；
- **端口 / 资源**：复用 `openfactory-api`（384M 上限），不新增常驻进程；
- **admin 构建**：`npm ci` / `npm run build` 属重活，脚本优先走 `bacs-heavy`，不并发。
