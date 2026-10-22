# 实施计划 · REQ-202610-0971 浏览器扩展（一键收藏当前页面）

> 需求：REQ-202610-0971（backlog M8-02）｜ 分支：`feat/req-202610-0971-browser-extension`
> 依赖：M5-05 接口限流与安全加固（已完成）｜ 基线：`feat/req-202610-0969-m7-acceptance` @ `af466cb`
> 目标：在 Chrome / Edge 中安装扩展后，浏览 GitHub / Gitee 仓库页时可一键把当前仓库收藏到
> OpenFactory 的「我的仓库」，并在弹窗中看到已收藏状态。

## 1. 现状与缺口

- 收藏入口目前只有 admin 内的「热榜详情 / 推荐」按钮，用户在其他标签页浏览仓库时需要
  先切回后台、搜索、再收藏，路径长；
- 边缘 API 只支持 httpOnly 会话 Cookie，浏览器扩展无法可靠携带（SameSite=Lax + 跨站子资源），
  需要一条**面向扩展的、可撤销的令牌**通道；
- `my_repositories` 以 `owner/repo` 为主键，跨用户重复收藏同一仓库时需要显式冲突处理，
  不能静默把仓库从其他用户名下转走；
- 项目还没有 `extension/` 目录、Manifest 与安装说明。

## 2. 方案总览

```
Chrome / Edge（Manifest V3，零构建，extension/）
  ├─ popup            当前标签页 → 解析 GitHub / Gitee 仓库 → 预览 → 一键收藏
  ├─ background       读取本地设置、携带 Bearer 令牌调用 edge、快捷键直接收藏
  ├─ options          API 地址 + 扩展令牌（申请动态 host 权限）
  └─ lib/repo.js      纯函数：URL 解析 / 元数据归一 / 计数格式化 / 地址校验
        │
        ▼  POST /api/extension/bookmark（Authorization: Bearer ofx_…）
edge（Cloudflare Worker）
  ├─ /api/extension/tokens  会话登录态：创建 / 列表 / 撤销扩展令牌（明文只返回一次）
  ├─ /api/extension/me      Bearer：连接测试 + 当前用户 + 令牌信息
  ├─ /api/extension/check   Bearer：查询 owner/repo 是否已收藏
  └─ /api/extension/bookmark Bearer：校验 / 归一化仓库元数据 → upsert my_repositories
        │
        ▼
D1：extension_tokens（token 仅存 sha-256 摘要）+ my_repositories
admin /settings/extension：生成令牌、复制安装步骤、撤销令牌
```

设计原则：

1. **最小权限**：扩展令牌只能访问 `/api/extension/*` 的收藏相关接口，不是通用开放 API；
2. **令牌不落明文**：D1 只存 `sha-256(token)`，创建时明文仅返回一次；后台列表只显示尾号提示；
3. **不读取页面 Cookie**：扩展使用 Bearer 令牌，不申请 `cookies` 权限，也不接触会话 Cookie；
4. **零依赖 / 零构建**：扩展使用原生 ES Module + `chrome.*` API，仓库内直接 `node --test` 测纯函数，
   用户以「加载已解压的扩展程序」安装，不需要额外打包链；
5. **优雅降级**：未配置 / 令牌失效 / 非仓库页面 / 已收藏 / 跨用户冲突都有明确状态与操作指引；
6. **可测试**：URL 解析、元数据归一化、计数解析、令牌提示等全部抽成纯函数。

## 3. 数据模型

`extension_tokens`（D1 迁移 `0022_extension_tokens.sql`）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | TEXT PK | `tok_<随机>` |
| `user_id` | TEXT NOT NULL | 所属用户 |
| `label` | TEXT | 备注（如「工作电脑 Chrome」） |
| `token_hash` | TEXT NOT NULL UNIQUE | `sha-256` 摘要，不存明文 |
| `hint` | TEXT NOT NULL | 尾号提示（如 `ofx_…a1b2`） |
| `created_at` | TEXT NOT NULL | 创建时间 |
| `last_used_at` | TEXT | 最近使用时间 |
| `revoked_at` | TEXT | 撤销时间；非空即失效 |

索引：`(user_id, created_at DESC)`。

## 4. 接口契约

### 4.1 会话登录态（admin 使用）

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/extension/tokens` | GET | 当前用户的扩展令牌列表（不含明文） |
| `/api/extension/tokens` | POST | 创建令牌，`{ label? }`，返回 `{ token, item }`（明文仅此一次） |
| `/api/extension/tokens/:id` | DELETE | 撤销令牌（仅限本人） |

### 4.2 Bearer 令牌（扩展使用）

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/extension/me` | GET | 连接测试：`{ user, token }` |
| `/api/extension/check?id=owner/repo` | GET | `{ saved, repo? }` |
| `/api/extension/bookmark` | POST | 收藏仓库：`{ repo: { platform, fullName, url, description?, language?, stars?, forks?, topics? } }` |

`POST /api/extension/bookmark` 行为：

- 校验平台（`github` / `gitee`）、`owner/repo` 格式与 URL 主机；
- 归一化描述 / 语言 / 计数 / topics，长度与数量截断；
- 已存在且属于当前用户 → 更新元数据并返回 `created: false`；
- 已存在但属于其他用户 → `409 repo_owned_by_other_user`（不转移归属）；
- 成功写入 `my_repositories`，返回 `{ ok, created, repo }`。

### 4.3 CORS

全局 CORS 在原有 `ALLOWED_ORIGIN` 精确回显的基础上，额外允许 `chrome-extension://` /
`moz-extension://` 来源（仅回显该来源，不放开 `*`），并继续允许 `Authorization` 头。

## 5. 扩展端

| 文件 | 说明 |
| --- | --- |
| `extension/manifest.json` | MV3：`activeTab` / `scripting` / `storage`，快捷键 `Ctrl+Shift+O` |
| `extension/src/lib/repo.js` | URL 解析、仓库元数据归一、Star 计数解析、API 地址 / 令牌校验 |
| `extension/src/content/extract.js` | 在页面上下文提取 canonical / 描述 / 语言 / Star / topics |
| `extension/src/background.js` | 设置读取、Bearer 请求、快捷键一键收藏、徽标反馈 |
| `extension/src/popup.html` / `popup.js` / `popup.css` | 弹窗：仓库预览、收藏状态、错误指引 |
| `extension/src/options.html` / `options.js` / `options.css` | API 地址与令牌配置、连接测试、动态 host 权限 |
| `extension/tests/repo.test.mjs` | 纯函数测试（GitHub / Gitee / 非仓库页 / 计数 / 归一化） |
| `extension/README.md` | 安装、配置、权限与故障排查 |

## 6. admin 设置页

- `/settings/extension`：说明安装步骤、当前 API 地址、令牌列表、创建 / 复制 / 撤销；
- 新增 `admin/src/features/extension/`（api + 页面 + 工具函数 + Vitest）；
- 设置侧边栏新增「Browser Extension」入口。

## 7. 测试与验收

| 层 | 用例 |
| --- | --- |
| extension | GitHub / Gitee URL 解析、保留路径排除、非仓库页、计数解析、元数据截断、令牌 / API 地址校验 |
| edge | 归一化与 URL 校验纯函数；令牌创建 / 列表 / 撤销 / Bearer 鉴权 / check / bookmark 路由（fake D1） |
| admin | 令牌提示格式化、状态文案、标签校验；lint / build / Vitest |
| 回归 | edge `npm run typecheck` + `npm test`；admin `npm run lint` + `npm run build` + `npm run test`；vps `pytest -q` |

验收标准：

1. 扩展安装后配置 API 地址与令牌，打开任意 GitHub / Gitee 仓库页，弹窗显示仓库信息；
2. 点击「收藏到 OpenFactory」后写入当前用户的 `my_repositories`，重复点击不重复创建；
3. 快捷键 `Ctrl+Shift+O` 可直接收藏当前仓库并给出徽标反馈；
4. 未配置 / 令牌失效 / 非仓库页 / 跨用户冲突均有可读提示；
5. 令牌只在创建时显示一次，列表仅显示尾号，撤销后立即失效；
6. 三端检查全绿，文档同步更新。

## 8. 风险与后续

- **扩展分发**：本期为开发者模式加载已解压目录，未上架 Chrome Web Store；上架需商店账号与隐私说明；
- **跨用户同仓库**：受 `my_repositories.id = owner/repo` 主键限制，第二位用户收藏同一仓库会得到 409；
  若后续支持多用户共享实例，需要评估复合主键迁移（登记 open-questions）；
- **页面结构变化**：GitHub / Gitee DOM 可能调整，提取器提供多组选择器与 meta 兜底，失败时仍可用
  URL + 页面标题收藏；
- **令牌范围**：本期令牌仅用于扩展收藏接口，M8-05 开放 API 可在同一 `extension_tokens` 思路上扩展
  作用域与配额，不直接复用明文。
