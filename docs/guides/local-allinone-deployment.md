# 本机一体化部署指南（离线自托管）

> 对应需求：REQ-202610-0940（backlog M5-02 / Q9 选项 B）｜ 维护人：fntp
> 适用版本：v0.1.x（M5 阶段）｜ 默认状态：**关闭**（保持混合架构 A）

本指南给出「本机一体化」模式的评估结论、部署步骤、资源与安全边界，以及升级 / 回滚 /
离线验收清单。实现上复用现有 `openfactory-api` 进程：开启 `LOCAL_MODE=1` 后，同一端口
同时托管 admin 静态页面与 edge 兼容的只读 API，不新增常驻进程。

## 1. 评估结论（Q9 A / B / C）

| 维度 | A. 混合架构（默认） | B. 本机一体化（本需求落地） | C. 其他 |
| --- | --- | --- | --- |
| 页面托管 | Cloudflare Pages | 本机 `openfactory-api` 静态托管 | 维护者指定 |
| 鉴权 | GitHub OAuth + 会话（edge） | 本机单用户，无 OAuth | 维护者指定 |
| 数据主库 | Cloudflare D1 | 本机 SQLite 镜像 | 维护者指定 |
| 离线可用 | ❌ 断网 / 无 Cloudflare 凭据即不可用 | ✅ 仅本机即可打开 admin 与读数据 | — |
| 数据主权 | 元数据在 D1，私有配置在本机 | 全部数据与配置在本机 | — |
| 资源占用 | VPS 仅算力节点 | 复用 `openfactory-api`（≤384M），无新增进程 | — |
| 运维复杂度 | 三端发布（Pages / Workers / VPS） | 单机一条命令构建 + 重启 | — |
| 功能完整度 | 全量（写操作 / OAuth / 推送 / 通知） | **只读首版**：仪表盘 / 仓库 / 热榜 / 推荐 / 分类 | — |
| 迁移成本 | — | 构建 admin 时改 `VITE_API_BASE_URL=/local`；数据沿用本地镜像 | — |
| 故障面 | Cloudflare + 本机 | 仅本机（单点） | — |

**结论**：

- B 模式已可落地，满足「部署在本机」的增强口径；断网时仍可浏览本机数据；
- 首版为**只读**，收藏 / 分类编辑 / 推荐反馈等写操作仍走 edge 或后续迭代；
- 默认保持 A（`LOCAL_MODE=0`），由维护者按需切换；两种模式共用同一份 SQLite，
  切换只改一个环境变量并重启 API，不迁移数据。

## 2. 拓扑与接口边界

```
┌──────────────────── 本机单进程（openfactory-api）────────────────────┐
│  GET /                      admin/dist 静态资源（SPA 回退）           │
│  GET /local/api/*           edge 兼容只读 API（单用户、本机信任）      │
│  GET /api/*                 既有 VPS 任务 / 检索 API（X-Internal-Token）│
│  GET /healthz               健康检查                                   │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ SQLAlchemy
                     /opt/openfactory/data/*.db（SQLite）
```

| 路径 | 用途 | 鉴权 |
| --- | --- | --- |
| `/`、`/assets/*`、`/trending/*` 等 | admin 构建产物与 SPA 回退 | 无（仅本机监听） |
| `/local/api/auth/me`、`/auth/logout` | 本机单用户身份 / 空登出 | 无 |
| `/local/api/repos`、`/trending*`、`/recommendations*`、`/categories`、`/dashboard/stats` | 只读数据接口 | 无（`LOCAL_MODE=1` 才注册） |
| `/local/api/local/status` | 模式 / 版本 / 构建产物状态 | 无 |
| `/api/*` | VPS 内部任务与检索接口 | `X-Internal-Token` |

`LOCAL_MODE=0` 时 `/local/api/*` 与静态托管均不注册，访问返回 404，混合架构行为不变。

## 3. 前置条件

- 已按 [deployment-baseline.md](./deployment-baseline.md) 完成运行目录、Redis 与
  `openfactory-*` systemd 单元；
- `/opt/openfactory/.env` 已由 `deploy/scripts/bootstrap-runtime.sh` 渲染；
- 本机已安装 Node.js / npm（仅构建 admin 时需要）；
- 本机已有 SQLite 镜像数据（同步 / 热榜任务至少跑过一次）。

## 4. 部署步骤

```bash
# 1) 构建 admin（VITE_API_BASE_URL=/local、VITE_DEMO_MODE=false）并复制到运行目录
deploy/scripts/local-allinone.sh build

# 2) 打开本机一体化模式并重启 openfactory-api（需 root）
sudo deploy/scripts/local-allinone.sh enable

# 3) 查看开关 / 构建产物 / 健康状态
deploy/scripts/local-allinone.sh status

# 4) 离线冒烟（healthz + 5 个只读接口 + admin 首页）
deploy/scripts/local-allinone.sh verify
```

浏览器访问 `http://127.0.0.1:8000/`。如需从局域网访问，请使用 SSH 隧道
（`ssh -L 8000:127.0.0.1:8000 <host>`），不要直接把端口暴露到公网。

`build` 会自动优先使用 `bacs-heavy`（同机资源自律：最多 2 个重活、`nice` + `ionice`）。

## 5. 配置项

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `LOCAL_MODE` | `0` | `1` 开启 `/local/api/*` 与 admin 静态托管 |
| `LOCAL_USER_ID` | `local` | 本机单用户 ID（`/auth/me` 返回） |
| `LOCAL_USER_LOGIN` | `local` | 本机单用户登录名 |
| `LOCAL_USER_NAME` | `本机用户` | 本机单用户显示名 |
| `LOCAL_ADMIN_DIR` | `@RUNTIME_DIR@/admin` | admin 构建产物目录；留空时用仓库内 `admin/dist` |

两份 env 模板（`vps/.env.example`、`deploy/env/openfactory.env.example`）与
`vps/app/config.py` 的字段由 `vps/tests/test_deploy_assets.py` 自动校验。

## 6. 资源占用

| 项目 | 预算 | 说明 |
| --- | --- | --- |
| API 进程 | ≤384M（沿用 `openfactory-api.service`） | 静态文件由 FastAPI 直接返回，无额外服务 |
| admin 构建产物 | 约 2–5M 磁盘 | `admin/dist` 复制到 `/opt/openfactory/admin` |
| 数据库 | 沿用 SQLite | 只读查询，不新增表 |
| 网络 | 0（离线可用） | 页面与接口均同源，不依赖 Cloudflare |

不新增 systemd 单元、不新增端口、不新增 Redis 队列；4G / 15G 资源红线不受影响。

## 7. 安全边界

- **仅监听回环地址**：`openfactory-api` 绑定 `127.0.0.1:8000`；本机模式没有登录态，
  直接暴露公网等于把全部收藏与推荐数据公开；
- 如需远程访问，使用 SSH 隧道或带认证的反向代理（Basic Auth / mTLS），并在反代层限流；
- `/local/api/*` 只读，不提供收藏、编辑、删除等写操作；
- `/api/*` 的内部令牌机制保持不变，`INTERNAL_TOKEN` 不得写入前端构建；
- admin 构建命令显式设置 `VITE_DEMO_MODE=false`，避免误用演示数据。

## 8. 升级与回滚

```bash
# 升级：拉取新代码后重新构建 + 重启（数据不动）
git pull
deploy/scripts/local-allinone.sh build
sudo systemctl restart openfactory-api

# 回滚到混合架构：关闭开关并重启
sudo deploy/scripts/local-allinone.sh disable

# 回滚构建产物：重新 checkout 上一版本后执行 build
```

回滚不需要迁移数据库；`LOCAL_MODE=0` 后 admin 仍由 Cloudflare Pages 提供，VPS 恢复为
纯算力节点。建议升级前对 `/opt/openfactory/data/opensource_factory.db` 做一次快照。

## 9. 离线验收清单

- [ ] `systemctl status openfactory-api` 为 active，`/healthz` 返回 `{"status":"ok"}`；
- [ ] `curl -s http://127.0.0.1:8000/local/api/local/status` 返回 `mode=local`、`readOnly=true`、`adminReady=true`；
- [ ] `curl -s http://127.0.0.1:8000/local/api/dashboard/stats` 的 `totalRepos` 与本地库一致；
- [ ] `/local/api/repos`、`/trending`、`/recommendations`、`/categories` 均返回数组 / 对象而非 5xx；
- [ ] 浏览器打开 `/`，仓库、热榜、推荐、分类、仪表盘五个页面可读取本机数据；
- [ ] 断开外网后重复上述检查仍全部通过；
- [ ] `deploy/scripts/local-allinone.sh verify` 退出码为 0。

## 10. 已知限制

- 只读首版：收藏 / 忽略 / 分类编辑 / 通知等写路径未在本机实现，页面上的写操作会失败；
- 数据以 VPS SQLite 镜像为准：D1 主库不会自动回流，离线期间的新数据需由本机任务抓取；
- 单用户信任模型：不区分账号，适合「一台机器一个人」的使用场景；
- admin 构建需要 Node.js 与 npm 依赖，首次 `npm ci` 需要可用的 npm 源（或本地缓存）。
