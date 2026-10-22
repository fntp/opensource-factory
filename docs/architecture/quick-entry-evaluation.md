# 快捷入口评估 · Raycast / 快捷指令类（M8-04）

> 需求：REQ-202610-0973 ｜ 评估日期：2026-10-22 ｜ 复跑：`cd vps && python -m app.quick_entry_eval report`

## 1. 结论摘要

**M8-05 开放 API 尚未落地，快捷入口全部被阻塞；建议先按契约完成个人令牌与 `/api/v1/*`，再启动 Raycast 扩展 MVP。**

- 首选：**Raycast 扩展**（4.10 / 5）
- 次选：**Apple 快捷指令**（3.95 / 5）
- 暂缓：VS Code 扩展、Alfred Workflow、uTools 插件（等首发平台验证后再评估）
- 总工作量估算：**8–13 人日**（含 M8-05 开放 API；不含商店审核等待）
- M8-05 API 就绪度：**0/16**；未就绪时所有快捷入口均被阻塞

## 2. 评估方法与权重

每项 1–5 分，按权重加权求和，满分 5.0；分数越高越适合作为首发入口。

| 维度 | 权重 | 说明 |
| --- | ---: | --- |
| 用户覆盖 | 20% | 目标用户规模与跨设备覆盖；只做 macOS 或只做 iOS 会丢一半场景 |
| 认证与密钥安全 | 20% | 是否支持个人令牌、能否安全存储、撤销与最小权限 |
| 交互效率 | 15% | 全局热键 / 分享面板 / 语音唤起 / 内联结果等快捷体验 |
| 开发成本 | 15% | 按人日估算的实现与联调成本，成本越低得分越高 |
| 维护与发布 | 10% | 商店审核、系统升级、API 变更带来的长期维护成本 |
| 安装门槛 | 10% | 用户从零到可用的步骤数；系统内置 / 商店一键安装得分更高 |
| 离线与降级 | 5% | 断网 / API 不可用时是否仍能给出本地缓存或明确提示 |
| 生态与扩展性 | 5% | 插件生态、深链、自动化组合与后续扩展空间 |

## 3. 候选平台排名

| 排名 | 平台 | 形态 | 覆盖 | 认证 | 体验 | 开发成本 | 维护 | 安装 | 离线 | 生态 | 加权分 | 等级 |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| 1 | Raycast 扩展 | 原生扩展（React / TypeScript） | 4 | 4 | 5 | 4 | 4 | 4 | 2 | 5 | **4.10** | A |
| 2 | Apple 快捷指令 | 系统快捷指令（HTTP 请求动作） | 5 | 2 | 3 | 5 | 5 | 5 | 3 | 4 | **3.95** | A- |
| 3 | 浏览器地址栏（omnibox） | 浏览器扩展的 omnibox 关键字 | 5 | 3 | 4 | 4 | 4 | 4 | 2 | 3 | **3.85** | A- |
| 4 | VS Code 扩展 | VS Code 扩展（命令面板） | 3 | 4 | 4 | 3 | 3 | 3 | 2 | 3 | **3.30** | B- |
| 5 | Alfred Workflow | Workflow（脚本 / 二进制） | 2 | 4 | 5 | 3 | 4 | 2 | 2 | 3 | **3.25** | B- |
| 6 | uTools 插件 | uTools 插件（JavaScript） | 3 | 3 | 4 | 3 | 3 | 4 | 2 | 3 | **3.20** | B- |

## 4. 分平台结论

### 4.1 Raycast 扩展（4.10 / A）

- 形态：原生扩展（React / TypeScript）；系统：macOS 12+；分发：Raycast Store 审核 + 本地 sideload
- 认证：扩展偏好中保存个人令牌（password 字段，仅本机）
- 估算工作量：4 人日
- 亮点：
  - 全局热键 + 列表式结果 + 动作面板，最接近「秒开秒搜」
  - TypeScript / React 技术栈与 admin 一致，复用成本低
  - 支持深链、剪贴板、选中文本与后续 AI Command
- 局限：
  - 仅 macOS，Windows / 移动端覆盖不到
  - 上架 Raycast Store 需要审核；可先 sideload 验证
  - 令牌保存在本机扩展偏好，需要明确告知用户风险
- 结论：首发首选：macOS 高频用户的价值最高，MVP 范围可控。

### 4.2 Apple 快捷指令（3.95 / A-）

- 形态：系统快捷指令（HTTP 请求动作）；系统：iOS / iPadOS 16+、macOS 13+；分发：系统内置，用户手动导入 / 分享
- 认证：快捷指令内保存个人令牌；可能随 iCloud 同步
- 估算工作量：2 人日
- 亮点：
  - iPhone / iPad / Mac 全覆盖，系统内置、零安装
  - 可挂到分享面板、Siri、主屏与自动化，触达路径最短
  - 无需代码与商店审核，1–2 人日即可产出可分享的指令
- 局限：
  - 令牌存在快捷指令里，iCloud 同步与分享都可能泄露
  - 多步表单体验弱，复杂筛选 / 分页不适合
  - 不同 iOS 版本的快捷指令动作存在差异，需要最低版本说明
- 结论：第二优先：作为 iOS / 非 Raycast 用户的兜底入口，只做搜索 + 收藏两个动作。

### 4.3 浏览器地址栏（omnibox）（3.85 / A-）

- 形态：浏览器扩展的 omnibox 关键字；系统：Chrome / Edge / Firefox；分发：浏览器扩展商店（复用 M8-02）
- 认证：扩展 storage 保存个人令牌
- 估算工作量：3 人日
- 亮点：
  - 所有桌面浏览器用户都能用，覆盖面最大
  - 可直接复用 M8-02 浏览器扩展的鉴权、API 与发布链路
  - 地址栏关键字 + 联想结果，输入成本低
- 局限：
  - 依赖扩展安装，纯移动端不可用
  - 浏览器扩展商店审核与 Manifest 版本升级需要持续维护
  - 令牌存于浏览器扩展，权限边界需要收紧
- 结论：不单独立项：作为 M8-02 浏览器扩展的一个 omnibox 入口顺带交付。

### 4.4 VS Code 扩展（3.30 / B-）

- 形态：VS Code 扩展（命令面板）；系统：Windows / macOS / Linux；分发：VS Code Marketplace 审核
- 认证：扩展设置保存个人令牌（SecretStorage 可选）
- 估算工作量：5 人日
- 亮点：
  - 开发者用户与收藏库重合度高
  - 命令面板 / 右键菜单适合「收藏当前仓库」
  - SecretStorage 可避免令牌明文落配置
- 局限：
  - 只覆盖开发者，且 VS Code 内已有 GitHub 插件竞争
  - Marketplace 审核与 Webview / API 兼容性维护成本较高
  - 与 M8-06 CLI 的用户场景重叠
- 结论：暂缓：等 M8-06 CLI 落地后复用同一套 API，再评估是否值得做扩展。

### 4.5 Alfred Workflow（3.25 / B-）

- 形态：Workflow（脚本 / 二进制）；系统：macOS；分发：自行分发；Powerpack 付费
- 认证：Workflow 配置或 Keychain 保存个人令牌
- 估算工作量：4 人日
- 亮点：
  - 老牌 macOS 启动器，热键与工作流体验成熟
  - 可直接调用系统 Keychain，令牌存储相对安全
- 局限：
  - 用户需要购买 Powerpack，安装门槛高
  - 用户规模明显小于 Raycast，投入产出比低
  - Workflow 脚本维护与 macOS 升级兼容需要长期投入
- 结论：暂缓：与 Raycast 用户高度重叠，等 Raycast 验证后再决定是否补位。

### 4.6 uTools 插件（3.20 / B-）

- 形态：uTools 插件（JavaScript）；系统：macOS / Windows；分发：uTools 插件应用市场审核
- 认证：插件配置保存个人令牌
- 估算工作量：5 人日
- 亮点：
  - 覆盖 Windows，可补 Raycast 的平台空白
  - 国内用户认知度高，插件安装与更新方便
- 局限：
  - 插件市场审核与平台规则不透明
  - API 能力与调试工具不如 Raycast 成熟
  - Windows 用户是否愿意为收藏工具安装启动器仍待验证
- 结论：观察：只有 Windows 需求被真实用户提出时再启动。

## 5. M8-05 API 就绪度

| 能力 | 分类 | 说明 | 就绪 | 阻塞平台 |
| --- | --- | --- | :---: | --- |
| `token.issue` | 令牌 | 登录后创建令牌，明文只返回一次，服务端只存 SHA-256 摘要 | ❌ | raycast、shortcuts、browser-omnibox、vscode、alfred、utools |
| `token.list` | 令牌 | 列出令牌名称 / 12 位指纹 / 最近使用时间 / 过期时间，不返回明文 | ❌ | raycast、shortcuts、browser-omnibox、vscode、alfred、utools |
| `token.revoke` | 令牌 | 立即撤销单个令牌，撤销后 60 秒内所有客户端失效 | ❌ | raycast、shortcuts、browser-omnibox、vscode、alfred、utools |
| `auth.bearer` | 认证 | `Authorization: Bearer <token>` 访问 `/api/v1/*`，与 Cookie 会话并存 | ❌ | raycast、shortcuts、browser-omnibox、vscode、alfred、utools |
| `scope.read` | 认证 | `read:repos` / `read:trending` / `read:recommendations` / `read:search` | ❌ | raycast、shortcuts、browser-omnibox、vscode、alfred、utools |
| `scope.write` | 认证 | `write:bookmarks` 仅允许收藏 / 取消收藏，不允许删除仓库或改分类 | ❌ | raycast、shortcuts、browser-omnibox、vscode、alfred、utools |
| `rate_limit` | 可靠性 | 读 60 次/分钟、写 20 次/分钟，返回 429 + Retry-After | ❌ | raycast、shortcuts、browser-omnibox、vscode、alfred、utools |
| `idempotency` | 可靠性 | `Idempotency-Key` 去重，重复收藏返回同一结果而不是 409 | ❌ | raycast、shortcuts、browser-omnibox、vscode、alfred、utools |
| `search` | 接口 | `GET /api/v1/search?q=&limit=` 返回仓库卡片，语义 / 关键词降级 | ❌ | raycast、shortcuts、browser-omnibox、vscode、alfred、utools |
| `bookmark.create` | 接口 | `POST /api/v1/bookmarks` 接受 URL 或 `owner/name`，返回仓库与分类 | ❌ | raycast、shortcuts、browser-omnibox、vscode、alfred、utools |
| `bookmark.delete` | 接口 | `DELETE /api/v1/bookmarks/{id}`，幂等 | ❌ | raycast、shortcuts、browser-omnibox、vscode、alfred、utools |
| `me` | 接口 | `GET /api/v1/me` 用于客户端启动时校验令牌与显示登录用户 | ❌ | raycast、shortcuts、browser-omnibox、vscode、alfred、utools |
| `openapi` | 接口 | `GET /api/v1/openapi.json` 或 manifest，客户端可据此生成类型 / 做契约测试 | ❌ | raycast、browser-omnibox、vscode |
| `cors` | 安全 | 仅对 M8-02 扩展来源回显 CORS，不允许任意网页携带令牌调用 | ❌ | browser-omnibox |
| `deep_link` | 体验 | `openfactory://repo/{owner}/{name}` 从快捷入口跳回 admin 详情 | ❌ | raycast、shortcuts、alfred |
| `audit` | 安全 | 记录令牌指纹、路径、状态码、时间与 IP 哈希，支持按令牌筛选 | ❌ | raycast、shortcuts、browser-omnibox、vscode、alfred、utools |

按平台的阻塞情况：

| 平台 | 状态 | 覆盖率 | 缺失能力 |
| --- | :---: | ---: | --- |
| Raycast 扩展 | 被阻塞 | 0% | `token.issue`、`token.list`、`token.revoke`、`auth.bearer`、`scope.read`、`scope.write`、`rate_limit`、`idempotency`、`search`、`bookmark.create`、`bookmark.delete`、`me`、`audit`、`openapi`、`deep_link` |
| Apple 快捷指令 | 被阻塞 | 0% | `token.issue`、`token.list`、`token.revoke`、`auth.bearer`、`scope.read`、`scope.write`、`rate_limit`、`idempotency`、`search`、`bookmark.create`、`bookmark.delete`、`me`、`audit`、`deep_link` |
| 浏览器地址栏（omnibox） | 被阻塞 | 0% | `token.issue`、`token.list`、`token.revoke`、`auth.bearer`、`scope.read`、`scope.write`、`rate_limit`、`idempotency`、`search`、`bookmark.create`、`bookmark.delete`、`me`、`audit`、`openapi`、`cors` |
| VS Code 扩展 | 被阻塞 | 0% | `token.issue`、`token.list`、`token.revoke`、`auth.bearer`、`scope.read`、`scope.write`、`rate_limit`、`idempotency`、`search`、`bookmark.create`、`bookmark.delete`、`me`、`audit`、`openapi` |
| Alfred Workflow | 被阻塞 | 0% | `token.issue`、`token.list`、`token.revoke`、`auth.bearer`、`scope.read`、`scope.write`、`rate_limit`、`idempotency`、`search`、`bookmark.create`、`bookmark.delete`、`me`、`audit`、`deep_link` |
| uTools 插件 | 被阻塞 | 0% | `token.issue`、`token.list`、`token.revoke`、`auth.bearer`、`scope.read`、`scope.write`、`rate_limit`、`idempotency`、`search`、`bookmark.create`、`bookmark.delete`、`me`、`audit` |

## 6. 推荐落地路线

| 阶段 | 范围 | 依赖 | 工作量（人日） | 交付物 |
| --- | --- | --- | ---: | --- |
| M8-05 开放 API（前置依赖） | 个人令牌签发 / 列表 / 撤销、Bearer 认证、读写 scope、限流、幂等、搜索 / 收藏 / 热榜 / 推荐 / me、OpenAPI、审计 | M5-05 会话与限流基线 | 4–6 | `/api/v1/*` 契约与实现、令牌管理页、契约测试 |
| Raycast 扩展 MVP | 搜索收藏 / 热榜、收藏剪贴板 URL、取消收藏、打开 admin 详情、令牌设置与连通性检查 | M8-05 | 3–4 | 可 sideload 的 Raycast 扩展 + 安装说明 + 真机验收记录 |
| Apple 快捷指令 | 分享面板收藏当前链接、Siri 搜索收藏、查看今日推荐；只做两个最小动作 | M8-05 | 1–2 | 可分享的快捷指令文件 + 令牌填写与撤销说明 |
| 浏览器地址栏（并入 M8-02） | 在浏览器扩展中注册 omnibox 关键字，复用已有鉴权与 API | M8-02 浏览器扩展 | 0–1 | 扩展新增 `of` 关键字搜索与收藏命令 |
| Alfred / uTools / VS Code（暂缓） | 仅在 Raycast 验证后出现明确平台诉求时再评估 | Raycast MVP 数据 | 0–0 | 不排期；保留平台评分与触发条件 |

## 7. 安全与隐私边界

- 令牌明文只在创建时返回一次，服务端只存 SHA-256 摘要与 12 位指纹；
- 默认只读 scope；写令牌单独创建，且只能收藏 / 取消收藏；
- 令牌不得写入 URL、日志、截图或可分享的快捷指令；快捷指令只让用户本机粘贴；
- 撤销后 60 秒内失效；令牌列表只显示指纹、最近使用时间与过期时间；
- 浏览器扩展只允许 M8-02 的来源，禁止任意网页携带令牌调用；
- 所有客户端请求走 HTTPS；服务端按令牌限流并记录审计事件。

## 8. 风险登记

| # | 风险 | 影响 | 概率 | 缓解 |
| --- | --- | :---: | :---: | --- |
| R1 | 令牌泄露（快捷指令 iCloud 同步 / 扩展偏好） | 高 | 中 | 只发最小 scope 令牌；默认只读，写令牌单独创建；提供一键撤销与最近使用审计；文档明确禁止把令牌写进 URL / 截图 / 分享的快捷指令 |
| R2 | M8-05 延期导致快捷入口无法开工 | 高 | 高 | 本需求只冻结契约与评分；M8-05 完成前不创建客户端分支；契约变更走版本号 |
| R3 | Raycast Store 审核周期不可控 | 中 | 中 | 先 sideload 给内测用户；商店审核与 MVP 开发解耦，审核不通过不影响自用 |
| R4 | 快捷指令版本差异导致动作不可用 | 中 | 中 | 最低版本写进说明（iOS 16 / macOS 13）；提供「复制 API 地址手动请求」的兜底步骤 |
| R5 | D1 / 搜索延迟导致快捷入口体感慢 | 中 | 中 | 客户端 200ms 防抖 + 本地缓存最近结果；服务端分页与 limit 上限；p95 目标 ≤ 800ms |
| R6 | 多客户端契约漂移 | 中 | 中 | 以 `/api/v1/openapi.json` 为唯一契约；每个客户端加契约测试；版本前缀 `/v1` 不兼容变更升 v2 |

## 9. 验收指标

| 指标 | 目标 | 采集方式 |
| --- | --- | --- |
| 激活率 | 创建令牌后 7 天内至少调用 1 次 | 令牌审计日志按指纹聚合 |
| 周活跃快捷入口用户 | 上线 4 周后 ≥ 10 人 | 按令牌指纹去重统计 |
| 命令成功率 | ≥ 99%（不含用户取消） | 客户端上报 + 服务端状态码 |
| 搜索 p95 | ≤ 800ms（客户端体感） | 客户端埋点与服务端指标对照 |
| 撤销生效时间 | ≤ 60 秒 | 撤销后立即请求应返回 401 |
| 明文令牌泄露 | 0 起 | 日志扫描 + 安全审计 |

## 10. 复跑方式

```bash
cd vps
python -m app.quick_entry_eval report
python -m app.quick_entry_eval report --json
python -m app.quick_entry_eval report --ready all   # 模拟 M8-05 全部就绪
python -m app.quick_entry_eval contract --out docs/assets/quick-entry-api-contract.json
```

> 评分与权重是 2026-10 的产品判断，调整 `CRITERIA` / `PLATFORMS` 后复跑即可；
> 真机验收（Raycast Store、iPhone 快捷指令、Alfred / uTools）需在对应设备完成。
