# 实施计划 · REQ-202610-0977 M8 验收与回顾

> 需求：REQ-202610-0977（backlog M8-08）｜ 分支：`feat/req-202610-0977-m8-acceptance`
> 依赖：M8-01~07；本轮实际可集成的已交付分支为 M8-01~04
> 目标：把 M8「多端接入」已交付能力按依赖顺序集成到一条验收分支，产出可复跑的验收脚本、
> 验收报告与缺口登记，并同步项目文档；不虚报未交付能力。

## 1. 现状与范围

| 需求 | 交付状态 | 验收方式 |
| --- | --- | --- |
| M8-01 PWA 与移动端适配（REQ-202610-0970） | 分支 `47610b8` 已交付 | manifest / Service Worker / 离线页 / 安装引导 / 移动端导航静态检查 |
| M8-02 浏览器扩展（REQ-202610-0971） | 分支 `9e32d27` 已交付 | MV3 manifest / 扩展源码 / edge 令牌接口 / 迁移 / admin 令牌页检查 |
| M8-03 Telegram Bot（REQ-202610-0972） | 分支 `4d5942c` 已交付 | 命令解析 / 转义 / 分片纯函数、webhook 路由、迁移、admin 面板检查 |
| M8-04 快捷入口评估（REQ-202610-0973） | 分支 `240a91b` 已交付 | 评估工具实跑：6 平台排名、16 项 API 就绪度、报告与契约 |
| M8-05 开放 API（个人令牌） | 平台 pending，未合入 | 缺口（GAP），登记再验收条件 |
| M8-06 CLI 工具 | 平台 pending，依赖 M8-05 | 缺口（GAP），登记再验收条件 |
| M8-07 离线可用（PWA 缓存 + 本地数据） | 平台 pending | 缺口（GAP），登记再验收条件 |
| M8-08 M8 验收与回顾 | 本任务 | 验收脚本 + 报告 + 文档同步 |

验收分支基于 M7 验收 tip `1c5451c` 拉出，依次合并 `47610b8` / `9e32d27` / `4d5942c` / `240a91b`。
M8-05/06/07 在其他工作树中仍处于开发中且平台状态为 `pending`，本轮不合并、不预判，
统一登记 GAP，待平台状态与分支交付后再补验收。

## 2. 实现方案

### 2.1 分支集成

1. `git merge --no-ff 47610b8`（M8-01，PWA / 移动端）；
2. `git merge --no-ff 9e32d27`（M8-02，浏览器扩展）；
3. `git merge --no-ff 4d5942c`（M8-03，Telegram Bot）；
4. `git merge --no-ff 240a91b`（M8-04，快捷入口评估）。

冲突处理原则：代码按能力并集合并；文档以 M7 验收后的最新版本为基线，M8 内容在验收收尾时统一补齐，
避免各分支基于旧版文档互相覆盖。

### 2.2 一致性整理

- **迁移编号**：M7 已占用 `0016`~`0020`，M8-03 使用 `0021_telegram_bot.sql`；
  M8-02 的 `0016_extension_tokens.sql` 与 M7-01 重号，顺延为 `0022_extension_tokens.sql`，
  同步 `docs/assets/d1-schema.sql`、`docs/architecture/data-model.md` 与计划文档引用；
- **迭代编号**：M7 使用 `IT-0054`~`IT-0063`；M8 占用 `IT-0064`~`IT-0071`，按交付顺序编号
  （`IT-0064` 已用于先期交付的 M8-04），本任务补齐 M8-01~03 / M8-05~08 条目，
  M8-05/06/07 标注平台 pending；
- **路由生成物**：`admin/src/routeTree.gen.ts` 在合并后由 `vite build` 重新生成，不手改；
- **架构文档**：`overview.md` 保留 M8-01 / M8-02 / M8-03 章节，补充 M8-04 评估入口；
  `data-model.md` 的 M8 两张表顺延为 3.25 / 3.26。

### 2.3 验收脚本

新增 `vps/scripts/m8_acceptance.py`（仅标准库 + 项目自身模块），覆盖：

- M8-01：manifest 字段与图标、Service Worker 预缓存 / `/api` 排除、离线页、PWA Provider、
  移动端底部导航、入口集成；
- M8-02：MV3 manifest、扩展核心源码、edge 六个令牌接口、迁移 `0022`、CORS 扩展来源、admin 令牌页；
- M8-03：Bot 命令解析 / HTML 转义 / 分片纯函数、webhook 等四类路由、迁移 `0021`、
  webhook 免 IP 限流、wrangler 变量、admin 面板；
- M8-04：`build_evaluation()` 排名（Raycast 4.10 首选 / 快捷指令 3.95 次选）、
  16 项 API 前置能力、0/16 就绪、契约 schema 与 10 个端点；
- 跨切面：edge 路由挂载、admin 路由树、迁移编号唯一、文档状态；
- 缺口：M8-05/06/07 未合入 → GAP。

脚本支持 `--strict`、`--report-md`、`--report-json`，判定口径为 PASS / FAIL / GAP。

## 3. 交付物

| 文件 | 说明 |
| --- | --- |
| `vps/scripts/m8_acceptance.py` | M8 可复跑验收脚本 |
| `docs/planning/acceptance-m8.md` | 验收结论、矩阵、集成修复、缺口与回顾 |
| `docs/planning/acceptance-m8-report.md` / `.json` | 脚本生成的原始报告 |
| `docs/planning/plan-req-202610-0977-m8-acceptance.md` | 本计划 |
| `docs/planning/roadmap.md` | M8 进度与更新记录 |
| `docs/planning/task-planning.md` | IT-0064~IT-0071 与交付记录 |
| `docs/requirements/backlog.md` | M8-01~04 / M8-08 完成，M8-05~07 保持 pending |
| `docs/requirements/open-questions.md` | M8 验收遗留问题（如有） |
| `docs/architecture/overview.md` | M8 架构章节与接口边界补充 |
| `docs/README.md` | 验收报告与计划索引 |

## 4. 验证计划

```bash
cd vps && .venv/bin/pytest -q
cd vps && .venv/bin/python scripts/m8_acceptance.py \
  --report-md docs/planning/acceptance-m8-report.md \
  --report-json docs/planning/acceptance-m8-report.json
cd edge && npm run typecheck && npm test
cd admin && npm run lint && npm run build && npm test
git diff --check
```

## 5. 边界

- 不实现 M8-05/06/07，不合并其未完成工作树；缺口如实登记；
- 不修改已交付分支的历史，不删除他人分支，不强推；
- 真机验收（浏览器安装 PWA / 加载扩展 / Telegram 实聊 / Raycast）本机无法完成，
  列入「仍需人工处理」；
- 验收脚本不访问网络、不依赖 Cloudflare / Telegram / GitHub 凭据，可离线复跑。
