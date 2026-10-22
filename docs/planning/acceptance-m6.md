# M6 验收与回顾（REQ-202610-0959）

> 验收日期：2026-10-22 ｜ 分支：`feat/req-202610-0959-m6-acceptance`
>
> 关联需求：`docs/requirements/backlog.md` · M6-12（M6 · 检索与知识库深化）｜ 依赖：M6-01~11
>
> 自动报告：`acceptance-m6-report.md` / `acceptance-m6-report.json`（由 `vps/scripts/m6_acceptance.py` 生成）

## 1. 结论

M6-01~M6-08 已全部集成到验收分支，跨分支端到端验收 **18/18 PASS、0 FAIL**；
M6-09~M6-11 在验收时平台状态仍为 `pending`，登记为 **3 项缺口（GAP）**，
不计入通过率、不虚报完成。M6-12 的验收范围、原始报告与复跑方式已固化。

| 检查 | 结果 |
| --- | --- |
| M6 验收脚本 | **18 PASS / 0 FAIL / 3 GAP** |
| VPS pytest | **482 passed**（10 warnings，无失败） |
| Edge `tsc --noEmit` | 通过 |
| Edge `node --test` | **108 passed** |
| Admin `eslint .` | 通过 |
| Admin `tsc -b && vite build` | 通过 |
| Admin Vitest（headless） | **156 passed**（24 files） |

验收环境：Linux x86_64 · Python 3.12.3 · 临时 SQLite + 真实 `uvicorn`；
M6-01/02/03/05/06/07 走 API 契约与行为断言，M6-04/08 走 edge / admin 资产与单测检查。

## 2. 验收矩阵

| 编号 | 能力 | 验收方式 | 结果 |
| --- | --- | --- | --- |
| M6-01 | 全文检索 | `repo_readmes` + FTS5 trigram 虚表与 3 个同步触发器；中文短词 `支付` 走 LIKE 回退命中 2 条；英文 `payment` 走 FTS 命中 2 条；状态 / 重建接口契约 | PASS |
| M6-02 | 相似项目推荐 | 种子向量存在时 `/api/search/similar` 返回近邻（Top1 `payment-kit-js`，score 0.988）；种子不存在 404、未向量化 409 | PASS |
| M6-03 | 重复 / 相似检测 | `/api/duplicates/scan` 形成重复簇（confidence 0.887），返回保留项、合并目标与字段级建议 | PASS |
| M6-04 | 技术栈图谱 | edge `GET /api/tech-stack` 聚合 + 纯函数目录；admin `/tech-stack` 页面与单测资产齐全 | PASS |
| M6-05 | 项目健康度 | `/api/repos/health` 列表 / 汇总 / 单仓库 / 刷新入队契约；active / stale / archived 分档正确 | PASS |
| M6-06 | License 合规 | 目录 6 类 16 条；汇总 total 4、high 1（AGPL）；单仓库 MIT → permissive / low 与义务提示 | PASS |
| M6-07 | 依赖分析 | 聚合返回 summary（2 仓库 / 6 依赖行）、techStack、ecosystems、dependencies、依赖 × 语言 links；扫描接口对不存在仓库安全返回 0 | PASS |
| M6-08 | 知识库导出 | edge `/api/export/knowledge` + `openfactory.knowledge.v1` 构建器；admin 导出页 / 单测；`guides/knowledge-export.md` 格式规范 | PASS |
| M6-09 | 多轮问答式检索 | 分支 `feat/req-202610-0956-conversational-search` 未合并，平台状态 pending | GAP |
| M6-10 | 检索体验精修 | 分支 `feat/req-202610-0957-search-ux` 未合并，平台状态 pending | GAP |
| M6-11 | 主题聚类与自动标签 | 分支 `feat/req-202610-0958-theme-clustering` 无提交，平台状态 pending | GAP |
| M6-12 | 验收与回顾 | 本文件 + 计划 + 自动报告 + 三端检查 | PASS |

## 3. 集成修复记录

本轮按依赖顺序合并 0948~0955 八个分支，发现并修复：

1. **`vps/app/api/repos.py` 装饰器缺失**：M6-06 的 License 路由合并后丢失
   `@router.get(`，且重复导入 `RepoOut` / `TaskEnqueued`；已补装饰器并收敛导入。
2. **`vps/app/api/tasks.py` 路由块断裂**：`/enrich-licenses` 前缺少 `@router.post(`，
   上一个处理函数缺少 `return TaskEnqueued(...)`；已补齐。
3. **`vps/app/main.py` 重复导入块**：`from app.api import (` 连续出现两次并残留半截列表；
   已合并为单块。
4. **`edge/src/types.ts` 字段错位**：`license` 被并入 `RepoHealthSummary` 而非
   `RepoItem`，导致 edge 类型检查失败；已移回 `RepoItem`。
5. **admin 路由树滞后**：`duplicates` / `licenses` 路由文件已合并但 `routeTree.gen.ts`
   未包含，`tsc -b` 失败；用 Vite 重新生成后恢复。
6. **健康度鉴权测试补丁点漂移**：`test_health_api_requires_internal_token` 仍 patch
   `app.api.tasks.get_settings`，而 `require_internal_token` 已收敛到 `app.security`；
   改为 patch `app.security.get_settings`。

迁移编号统一：重复检测忽略记录 `0013`、健康度 `0014`、License `0015`；
`open-questions.md` 新增 Q24~Q30，分别记录 FTS、重复检测、技术栈、健康度、
License、依赖分析与知识库导出的取舍和阈值。

## 4. 缺口与再验收条件

| 缺口 | 平台状态 | 再验收条件 |
| --- | --- | --- |
| M6-09 多轮问答式检索（REQ-202610-0956） | pending | 分支合入后，补「多轮上下文 / 追问改写 / 结果引用」API 契约与 admin 对话页检查，再跑 `m6_acceptance.py` |
| M6-10 检索体验精修（REQ-202610-0957） | pending | 分支合入后，补搜索建议 / 历史 / 快捷键的组件测试与键盘交互检查 |
| M6-11 主题聚类与自动标签（REQ-202610-0958） | pending | 分支有提交并合入后，补聚类结果稳定性、标签回写与 admin 主题页检查 |

## 5. 回顾

### 做得好的

- 八个 M6 分支按依赖顺序合并，检索底座（M6-01/02）先行，健康度 / License / 依赖分析
  在其上叠加，业务实现基本独立；冲突集中在 `schemas.py` / `models.py` / `types.ts` / 文档。
- 验收脚本复用 M5 的真实 `uvicorn` + 临时 SQLite 模式，一次运行覆盖 15 项运行时断言
  与 3 项静态资产检查，不依赖 GitHub / Cloudflare / LLM 外部凭据即可重复执行。
- 对未交付的 M6-09~11 明确登记 GAP 与再验收条件，避免把「分支存在」误当成「已交付」。

### 需要改进的

- 多分支合并后出现了 3 处 Python 语法级损伤（装饰器 / 导入块 / 返回值），说明
  「合并后先 `compileall` 再跑测试」应固化为验收第一步。
- `routeTree.gen.ts` 是生成物但被提交，跨分支合并时容易滞后；合并后应显式跑一次
  Vite 构建再执行 `tsc -b`。
- M6-09~11 的分支在平台仍为 pending 时已出现在本地，后续需在验收前先核对平台状态，
  避免验收范围与平台口径不一致。

## 6. 复跑方式

```bash
# VPS：完整测试 + M6 验收（在 vps/ 下，使用项目 venv）
pytest -q
python scripts/m6_acceptance.py --strict \
  --report-md docs/planning/acceptance-m6-report.md \
  --report-json docs/planning/acceptance-m6-report.json

# Edge
cd edge && npm ci && npm run typecheck && npm test

# Admin
cd admin && npm ci && npm run lint && npm run build && npm test
```

> 说明：`--strict` 会在存在 GAP 时返回非零，用于「M6 全量完成」门禁；
> 本轮部分验收使用不带 `--strict` 的方式生成报告，GAP 单独登记。

## 7. 遗留事项

- **M6-09~11 未交付**：平台状态 pending，需按第 4 节条件补充验收后，才能把 M6 标记为全部完成。
- **真实环境验收**：本轮使用临时 SQLite 与本地回环 HTTP，未覆盖真实 D1 / Vectorize /
  GitHub API 的线上流量；上线后需补一次 edge + VPS 联调冒烟。
- **迁移顺序**：`0013`~`0015` 需在部署时按编号顺序应用；D1 与 VPS SQLite 的
  补列逻辑已分别由 migration 与 `_ensure_sqlite_columns()` 覆盖。
