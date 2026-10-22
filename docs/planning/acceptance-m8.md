# M8 验收与回顾 · 多端接入

> 需求：REQ-202610-0977（backlog M8-08）｜ 分支：`feat/req-202610-0977-m8-acceptance`
> 验收日期：2026-10-22 ｜ 原始报告：[acceptance-m8-report.md](./acceptance-m8-report.md) · [acceptance-m8-report.json](./acceptance-m8-report.json)

## 1. 结论

**M8-01~04 已交付能力全部通过（13/13 PASS）；M8-05~07 平台状态仍为 pending，本轮判定为部分验收（有条件通过），登记 3 项 GAP。**

- 已集成并验收：M8-01 PWA / 移动端、M8-02 浏览器扩展、M8-03 Telegram Bot、M8-04 快捷入口评估；
- 未纳入验收：M8-05 开放 API、M8-06 CLI、M8-07 离线可用 —— 三者仍在其他工作树开发，平台状态 `pending`，本轮不合并、不预判；
- 真机环节（PWA 安装、扩展商店加载、Telegram 实聊）本机无法完成，列入第 6 节人工复核。

三端检查全绿：**vps 549 passed** · **edge 215 passed + typecheck** · **admin 249 passed + lint + build** ·
**extension 15 passed**。

## 2. 验收范围与方法

验收分支基于 M7 验收 tip `1c5451c` 拉出，按依赖顺序 `--no-ff` 合并四个已交付分支：

| 顺序 | 需求 | 交付分支 tip | 合并提交 |
| ---: | --- | --- | --- |
| 1 | M8-01 PWA 与移动端适配（REQ-202610-0970） | `47610b8` | `38206c0` |
| 2 | M8-02 浏览器扩展（REQ-202610-0971） | `9e32d27` | `140a7b2` |
| 3 | M8-03 Telegram Bot（REQ-202610-0972） | `4d5942c` | `9f0f249` |
| 4 | M8-04 快捷入口评估（REQ-202610-0973） | `240a91b` | `0641ef5` |

方法：`vps/scripts/m8_acceptance.py` 做跨分支静态资产检查 + M8-04 评估工具实跑；
不访问网络、不依赖 Cloudflare / Telegram / GitHub 凭据，可离线复跑。
判定口径：**PASS** 通过 · **FAIL** 行为错误 · **GAP** 未交付缺口（不计入通过率）。

## 3. 验收矩阵

| 编号 | 检查项 | 结果 | 关键证据 |
| --- | --- | --- | --- |
| M8-A01 | PWA manifest 与图标 | PASS | `admin/public/manifest.webmanifest`：standalone、192/512 + maskable、3 个快捷入口 |
| M8-A02 | Service Worker 与离线兜底 | PASS | `sw.js` App Shell 预缓存、`/offline.html`、`/api/*` 与非 GET 排除 |
| M8-A03 | 安装引导与移动端导航 | PASS | `PwaProvider`、`MobileTabBar`（`md:hidden` + 安全区）、生产环境 SW 注册 |
| M8-B01 | MV3 manifest | PASS | `extension/manifest.json`：MV3、activeTab / scripting / storage、background / action / options |
| M8-B02 | 扩展核心与单测 | PASS | `repo.js` 仓库解析、`content/extract.js` 元数据提取、`node:test` 用例 |
| M8-B03 | edge 令牌接口与迁移 | PASS | 迁移 `0022_extension_tokens.sql`、6 个接口、扩展来源 CORS、admin 令牌页 |
| M8-C01 | Bot 命令纯函数 | PASS | 命令解析 / HTML 转义 / 4096 上限与 3800 分片 / 六类消息 |
| M8-C02 | webhook 路由与迁移 | PASS | 迁移 `0021_telegram_bot.sql`、webhook / status / link-code / link、免 IP 限流、admin 面板 |
| M8-D01 | 评估工具实跑 | PASS | Raycast 4.10 首选、快捷指令 3.95 次选、6 平台、16 项 API、0/16 就绪 |
| M8-D02 | 报告与契约资产 | PASS | `quick-entry-evaluation.md`、`quick-entry-api-contract.json`（`openfactory.quick-entry.v1`，10 端点） |
| M8-S01 | edge / admin 路由集成 | PASS | `/api/extension`、`/api/telegram` 挂载；routeTree 含 `/settings/extension` 与 M7 页面 |
| M8-S02 | 迁移编号与 D1 schema | PASS | M8 迁移 `0021` / `0022` 编号唯一，`d1-schema.sql` 三张表同步 |
| M8-S03 | 需求与验收文档状态 | PASS | backlog M8-01~04 / M8-08 完成，M8-05~07 保持 pending |
| M8-05-GAP | 开放 API（个人令牌） | GAP | `feat/req-202610-0974-open-api` 未合并，平台 pending |
| M8-06-GAP | CLI 工具 | GAP | `feat/req-202610-0975-cli-tool` 未合并，依赖 M8-05 |
| M8-07-GAP | 离线可用（PWA 缓存 + 本地数据） | GAP | `feat/req-202610-0976-offline-pwa-local-data` 未合并，平台 pending |

## 4. 集成修复

1. **迁移编号冲突**：M8-02 原 `0016_extension_tokens.sql` 与 M7-01 `0016_tag_suggestions.sql` 重号，
   顺延为 `0022_extension_tokens.sql`，同步 `docs/assets/d1-schema.sql`、`data-model.md` 与计划文档引用；
2. **路由生成物**：合并后 `admin/src/routeTree.gen.ts` 缺少 `/settings/extension`，
   由 `vite build` 重新生成，未手改；
3. **文档冲突**：四个分支基于旧版 M7 文档，`roadmap` / `backlog` / `task-planning` / `data-model` /
   `d1-schema` / `README` 等以 M7 验收后版本为基线，M8 内容在本轮统一补齐；
4. **D1 schema 并集**：`extension_tokens`、`telegram_links`、`telegram_link_codes` 三张表全部保留，
   `data-model.md` M8 章节顺延为 3.25 / 3.26。

## 5. 缺口与再验收条件

| 缺口 | 当前状态 | 再验收条件 |
| --- | --- | --- |
| M8-05 开放 API（个人令牌） | 平台 pending，分支开发中 | 分支交付并合并后，补验令牌生命周期、`/api/v1/*` 契约与限流 |
| M8-06 CLI 工具 | 平台 pending，依赖 M8-05 | M8-05 验收通过后，补验登录 / 查询 / 收藏命令与错误码 |
| M8-07 离线可用 | 平台 pending | 分支交付后，补验离线写队列 / 本地数据合并与冲突处理 |

以上缺口不影响 M8-01~04 的已交付能力，但 M8 里程碑整体完成需待三项补齐后二次验收。

## 6. 仍需人工处理

- 在真实浏览器安装 PWA，验证离线刷新、安装引导与移动端底部导航；
- 在 Chrome / Edge 加载 `extension/` 未打包扩展，走通「生成令牌 → 收藏当前页」；
- 配置真实 Telegram Bot token / webhook secret，验证 `/link`、`/favorites`、`/recommend`、`/trending`；
- Raycast 扩展尚未开发（依赖 M8-05），M8-04 仅完成平台评估与契约。

## 7. 回顾

**做得好的：**

- 验收脚本只依赖标准库与项目模块，覆盖四个分支的关键行为，可离线复跑；
- 先做静态资产检查 + 评估工具实跑，能在不接触外部凭据的前提下发现集成问题；
- 缺口单独登记为 GAP，不把未交付能力计入通过率，避免虚报。

**暴露的问题：**

- 各分支从旧版 M7 文档拉出，文档冲突集中且重复，说明分支拉出时机与文档基线需要更早对齐；
- M8-02 迁移编号未先查已占用号段，导致重号返工；后续新迁移应先跑编号唯一性检查；
- `routeTree.gen.ts` 作为生成物在合并时容易带入旧版本，必须由构建重新生成而非手工解决冲突。

**改进项：**

- 需求分支开工前先 rebase / merge 最新 `main`，减少文档冲突；
- 在 CI 增加迁移编号唯一性与 `routeTree.gen.ts` 干净构建检查；
- 验收脚本继续沿用 PASS / FAIL / GAP 口径，作为后续里程碑的固定交付物。

## 8. 复跑方式

```bash
cd vps
python scripts/m8_acceptance.py \
  --report-md docs/planning/acceptance-m8-report.md \
  --report-json docs/planning/acceptance-m8-report.json

# 严格模式：存在 GAP 也返回非零（用于里程碑整体完成判定）
python scripts/m8_acceptance.py --strict
```

三端检查：

```bash
cd vps && .venv/bin/pytest -q
cd edge && npm run typecheck && npm test
cd admin && npm run lint && npm run build && npm test
```
