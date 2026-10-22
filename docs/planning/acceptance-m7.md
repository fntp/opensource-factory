# M7 验收与回顾（REQ-202610-0969）

> 验收日期：2026-10-22 ｜ 分支：`feat/req-202610-0969-m7-acceptance`
>
> 关联需求：`docs/requirements/backlog.md` · M7-10（M7 · 智能助理与自动化）｜ 依赖：M7-01~09
>
> 自动报告：`acceptance-m7-report.md` / `acceptance-m7-report.json`（由 `vps/scripts/m7_acceptance.py` 生成）
>
> 执行计划：`plan-req-202610-0969-m7-acceptance.md`

## 1. 结论

M7-01~M7-07 已全部集成到验收分支，跨分支端到端验收 **14/14 PASS、0 FAIL**；
M7-08（LoRA 微调评估）与 M7-09（Agent 工作流）在验收时平台状态仍为 `pending`，
登记为 **2 项缺口（GAP）**，不计入通过率、不虚报完成。M7-10 的验收范围、原始报告与复跑方式已固化。

| 检查 | 结果 |
| --- | --- |
| M7 验收脚本 | **14 PASS / 0 FAIL / 2 GAP** |
| VPS pytest | **532 passed**（10 warnings，无失败） |
| Edge `tsc --noEmit` | 通过 |
| Edge `node --test` | **180 passed** |
| Admin `eslint .` | 通过 |
| Admin `tsc -b && vite build` | 通过 |
| Admin Vitest（headless） | **224 passed**（33 files） |

验收环境：Linux x86_64 · Python 3.12.3 · 临时 SQLite + 真实 `uvicorn`；
M7-01/02/06/07 走 API 契约与行为断言，M7-03/04/05 走纯函数 / edge / admin 资产检查。

## 2. 验收矩阵

| 编号 | 能力 | 验收方式 | 结果 |
| --- | --- | --- | --- |
| M7-01 | 自动打标建议 | `/api/tag-suggestions/generate` 对 AI 仓库返回 Python / FastAPI / AI-LLM / 搜索，全部 ≥0.55 且带 reason / evidence；无命中语言不误报 | PASS |
| M7-02 | 自动分类建议 | `/api/category-suggestions/generate` 命中「AI / 大模型」与「金融 / 支付」，Top N ≤3、分数 ≥0.55、带业务线 / 理由 | PASS |
| M7-03 | 每周 / 月度精选报告 | edge `reports/generate.ts` 周 / 月纯函数、`/api/reports` + 内部生成接口、双 Cron、admin `/reports` 页面齐全 | PASS |
| M7-04 | 收藏项目更新提醒 | `parse_version` / `is_major_bump` / `classify_update` / `contains_breaking_change` / 摘要截断断言；迁移 `0019` | PASS |
| M7-05 | Star 趋势与洞察 | edge `insights/star-trends.ts` + `/api/star-trends` 路由 + admin `/star-trends` 页面齐全 | PASS |
| M7-06 | 模型路由与升级 | `/api/model-routes` 返回 6 个任务 / 10 个模型 / 预算字段；健康接口含 ollama / deepseek / rules；未知任务 404、未知模型 400、非法策略 422 | PASS |
| M7-07 | Rerank 精排 | `/api/recommend/rerank/preview` 4 条候选输出六路信号、理由、rankAfter 连续、MMR 后多样性 0.8317；`/apply` 保留 Top3 | PASS |
| M7-08 | 个人数据微调评估（LoRA） | 分支 `feat/req-202610-0967-lora-evaluation` 未合并，平台状态 pending | GAP |
| M7-09 | Agent 工作流 | 分支 `feat/req-202610-0968-agent-workflow` 未合并，平台状态 pending | GAP |
| M7-10 | 验收与回顾 | 本文件 + 计划 + 自动报告 + 三端检查 | PASS |

## 3. 集成修复记录

本轮从 M6 验收 tip `6d20e1a` 拉出验收分支，按依赖顺序合并 0960~0966 七个分支：

1. **`vps/app/schemas.py` 冲突块交错（M7-01/02）**：TagSuggestion 与 CategorySuggestion
   两段类定义共享 `score/reason/evidence` 字段，自动合并后残留第二段冲突标记与重复类；
   已按能力并集重建完整 block 并删除残留行。
2. **`admin/src/components/layout/data/sidebar-data.ts` 多层嵌套冲突（M7-02~06）**：
   多个分支各自追加菜单项，冲突标记层层嵌套无法正则清理；已整文件重写并统一菜单顺序
   （打标建议 / 分类建议 / 精选报告 / 更新提醒 / Star 趋势 / 模型路由 / 精排工作台）。
3. **`vps/app/db.py` 重复补列块（M7-04）**：分支自带 `my_repositories` 补列块，HEAD 已有
   `table_additions` 块；已删除重复块，将 Release 基线五列并入既有字典。
4. **`edge/src/index.ts` 路由挂载**：逐个合并 tag-suggestions / category-suggestions / reports /
   repo-updates / star-trends / rerank 六组导入与 `app.route`，保留全部能力。
5. **`vps/app/main.py` 路由去重**：`duplicates` 与 `tag_suggestions` 在多次合并中重复导入，
   已收敛为单次导入并按模块顺序挂载。
6. **`edge/src/types.ts` License 字段**：M7-05 分支将 `license?: LicenseInfo | null`
   并入 `RepoItem`，与 M6-06 的字段定义合并后保留单份。
7. **`admin/src/routeTree.gen.ts` 滞后**：新增 7 个路由文件后生成物未包含，
   `tsc -b` 报 4 处 `FileRoutesByPath` 错误；已用 `vite build` 重新生成后恢复。

跨分支一致性整理：

- **迁移编号**：M6 已占用 `0013` / `0014` / `0015`，M7 五个迁移顺延为
  `0016_tag_suggestions` / `0017_category_suggestions` / `0018_curated_reports` /
  `0019_repo_updates` / `0020_rerank`，同步 `docs/assets/d1-schema.sql`、`edge/README.md`
  与五份计划文档引用；
- **迭代编号**：M7-01~10 统一为 `IT-0054~IT-0063`，消除与 M6 `IT-0044~0052` 的重号；
- **架构文档**：`overview.md` M7 顺延为 3.29~3.33（备份 3.28 从部署拓扑归位），
  `data-model.md` 重排 3.1~3.24 并将 M7 四张表集中到 3.21~3.24；
- **open-questions**：Q1~Q9 保持稳定，Q10~Q34 按需求编号重排，删除重复的知识库导出条目，
  新增 Q31 标签治理 / Q32 报告周期 / Q33 Star 历史 / Q34 Rerank 调参；
- **文档索引**：`docs/README.md` 合并重复的 planning 行，`edge/README.md` 迁移清单按实际文件重写。

## 4. 缺口与再验收条件

| 缺口 | 平台状态 | 再验收条件 |
| --- | --- | --- |
| M7-08 个人数据微调评估（REQ-202610-0967） | pending | 分支合入后，补 LoRA 数据集构建 / 训练预算 / 效果评估报告检查，再跑 `m7_acceptance.py` |
| M7-09 Agent 工作流（REQ-202610-0968） | pending | 分支合入后，补工作流编排 / 自动整理 / 草稿生成的 API 契约与 admin 页面检查 |

## 5. 回顾

### 做得好的

- 七个 M7 分支按依赖顺序合并，打标 / 分类 / 报告 / 提醒 / 趋势 / 路由 / 精排逐层叠加；
  冲突集中在 `schemas.py` / `models.py` / `sidebar-data.ts` / 文档，业务实现基本独立。
- 验收脚本复用 M6 的真实 `uvicorn` + 临时 SQLite 模式，一次运行覆盖 9 项运行时断言
  与 5 项静态资产检查，不依赖 GitHub / Cloudflare / LLM 外部凭据即可重复执行。
- 对未交付的 M7-08/09 明确登记 GAP 与再验收条件，避免把「分支存在」误当成「已交付」。

### 需要改进的

- 多分支并行开发时迁移编号各自从 `0013` 起编，合并阶段才暴露冲突；应在分支创建时
  由平台预分配迁移号，或在 CI 增加「迁移前缀唯一」检查。
- `sidebar-data.ts` 与 `schemas.py` 是高频冲突文件，后续应按功能拆分模块，
  避免所有分支都改同一文件。
- `routeTree.gen.ts` 是生成物但被提交，合并后必须显式跑一次 `vite build` 再执行
  `tsc -b`；该步骤已写入本验收的复跑方式。
- 平台 pending 的 M7-08/09 在本地已有分支提交，验收前需先核对平台状态，
  避免验收范围与平台口径不一致。

## 6. 复跑方式

```bash
# VPS：完整测试 + M7 验收（在 vps/ 下，使用项目 venv）
pytest -q
python scripts/m7_acceptance.py --strict \
  --report-md docs/planning/acceptance-m7-report.md \
  --report-json docs/planning/acceptance-m7-report.json

# Edge：类型检查 + 纯函数测试
cd edge && npm run typecheck && npm test

# Admin：lint + 构建 + 浏览器测试
cd admin && npm run lint && npm run build && npm test
```

> 注：`--strict` 会因 M7-08/09 的 GAP 返回非零；若只验证已交付能力，去掉 `--strict` 即可。
