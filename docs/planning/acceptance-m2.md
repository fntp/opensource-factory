# M2 验收报告 · 热榜与摘要（端到端走查 + 性能抽样 + 回顾）

> 需求：REQ-202610-0918（M2-10）｜ 验收日期：2026-10-22
>
> 验收分支：`feat/req-202610-0918-m2-acceptance`（基于 `feat/req-202610-0746-writeback` @ `9e6c105`）
>
> 工作树：`/opt/workspace/opensource-factory-req0918`
>
> 原始报告：[acceptance-m2-report.md](./acceptance-m2-report.md) · [acceptance-m2-report.json](./acceptance-m2-report.json)

## 1. 结论

本轮在本地 D1 环境完成 M2 热榜主链路端到端走查：**24 项断言全部 PASS，0 GAP，0 FAIL，0 SKIP**；热榜列表 P95 38.3ms，低于 300ms 预算。M2-04~08 的 edge 对外契约与 D1 数据链路已实际运行通过；M2-01~03 的 VPS 抓取 / 容错 / 清洗能力由 98 个 pytest 用例覆盖。

M2-09（Gitee 探索页抓取）按 Q2 结论本期不接入，不在本轮范围。真实 GitHub / Cloudflare 生产凭据联调仍未覆盖，列入遗留。

## 2. 验收环境与方法

- 数据集：1 个测试用户 / 6 个热榜仓库 / 13 条快照（5 个日期，含 2 条过期）/ 1 条历史曲线；
- 运行时：`wrangler dev`（本地 D1，迁移 0001~0008 全量应用）；
- 请求方式：真实 HTTP，携带种子会话 Cookie 与 `X-Internal-Token`；性能抽样在预热后顺序执行 100 次，统计 P50 / P95 / Max；
- 通过标准：`--strict` 模式下 GAP 也视为失败；性能预算 P95 < 300ms。

## 3. M2 验收矩阵

| 编号 | 验收点 | 状态 | 证据 / 说明 |
| --- | --- | --- | --- |
| M2-01 | GitHub Trending 每日定时抓取（多语言页） | ✅ PASS | VPS `test_trending_job` / `test_trending_pages` 覆盖全局页 + 12 语言页、去重与落库；脚本验证快照 D1 契约 |
| M2-02 | 抓取容错与页面结构变更告警 | ✅ PASS | VPS `test_crawl_guard` 覆盖超时 / 429 / 5xx 重试、条数骤降、告警去重与 ack |
| M2-03 | README 清洗与技术栈提取 | ✅ PASS | VPS `test_readme` 覆盖徽章 / 图片 / HTML / 实体 / 零宽字符；详情接口透出 `techStack` |
| M2-04 | 中文摘要批量生成与质量抽检 | ✅ PASS | 脚本 M2-D01/D02：内部令牌校验、批量回写、详情摘要来源切换为 `readme`；VPS 摘要用例全绿 |
| M2-05 | 按日快照与趋势字段 | ✅ PASS | 脚本 M2-A01/A04/B01/B03/E02：快照日期、排名、`rankChange`、`isNew`、upsert 幂等 |
| M2-06 | 热榜页日期 / 语言筛选与趋势标注 | ✅ PASS | 脚本 M2-A02/A03/A05/A06/B02：日期、语言大小写、limit、非法日期 400、无数据不回退 |
| M2-07 | 热榜详情与一键收藏 | ✅ PASS | 脚本 M2-C01~C06：摘要三档回退、404、401、收藏幂等、取消收藏 |
| M2-08 | 数据保留 / 归档 / 清理 | ✅ PASS | 脚本 M2-E03~E05：状态统计、dryRun 不删除、实际清理与最早日期推进；VPS `test_trending_retention` 覆盖 gzip JSONL 归档 |
| M2-09 | Gitee 探索页抓取 | ➖ 不适用 | Q2 已确认本期不接入；`crawl_gitee_explore` 入口已预留 |
| M2-10 | M2 验收与回顾 | ✅ PASS | 本报告 + 计划 + 脚本 + 文档同步 |

## 4. 端到端走查明细（24 项）

| 分组 | 断言 | 结果 |
| --- | --- | --- |
| A 列表 / 趋势 | 默认最近一天、日期筛选、语言筛选、趋势四态、limit / 非法日期、无数据不回退 | 6 PASS |
| B 日期 / 语言 / 历史 | 日期倒序计数、语言分布、单仓库三点历史 | 3 PASS |
| C 详情 / 收藏 | README 摘要、description / tech 回退、404、401、收藏幂等、取消收藏 | 6 PASS |
| D 摘要回写 | 内部令牌校验、批量回写后详情生效 | 2 PASS |
| E 快照 / 保留 | 内部令牌、upsert 幂等、保留状态、dryRun、实际清理 | 5 PASS |
| F 兼容 / 性能 | 无快照回退最新状态表、列表 P95 < 300ms | 2 PASS |

## 5. 性能抽样

| 场景 | 样本数 | P50 | P95 | Max | 预算 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 热榜列表 limit=100 | 100 | 29.4ms | 38.3ms | 69.0ms | < 300ms |

## 6. 集成分支与提交

| 需求 | 分支 | 提交 | 集成内容 |
| --- | --- | --- | --- |
| M2-04 | `feat/req-202610-0912-summary-quality` | `8a443a2` | 摘要多来源批量、启发式评分、确定性抽检、人工复核 API |
| M2-01 / M2-05 | `feat/req-202610-0909-trending-daily-crawl` / `-0913-trending-snapshots` | `89e1efd` / `c913eef` | 每日多语言抓取、按日快照与趋势字段、D1 批量回写 |
| M2-02 | `feat/req-202610-0910-crawl-fault-tolerance` | `0c3d8a6` | 有限重试、解析诊断、`crawl_alerts` / `crawl_page_stats` |
| M2-03 | `feat/req-202610-0911-readme-cleaning` | `af63761` | README 去噪、技术栈别名归并 |
| M2-06 | `feat/req-202610-0914-trending-page` | `cfe01b8` | 日期 / 语言筛选、趋势标注、admin 热榜页 |
| M2-07 | `feat/req-202610-0915-trending-detail` | `8e3f138` | 详情摘要回退、一键收藏 / 取消、admin 详情页 |
| M2-08 | `feat/req-202610-0916-trending-retention` | `23b3d0c` | 保留窗口、gzip JSONL 归档、本地与 D1 清理、beat 定时 |

合并提交（`--no-ff`）：`8a45416` → `6f11cce` → `6e80ecc` → `b63a235` → `62fa32c` → `57d6e8f` → `0d3e6bd`。

## 7. 检查结果

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| admin lint | `cd admin && npm run lint` | ✅ 0 error |
| admin build | `cd admin && npm run build` | ✅ tsc + vite 通过 |
| admin test | `cd admin && npm run test` | ✅ 12 文件 / 82 用例 |
| edge typecheck | `cd edge && npm run typecheck` | ✅ 0 error |
| edge 脚本测试 | `cd edge && npm run test:trending` | ✅ 11 用例 |
| M2 验收 | `cd edge && npm run test:m2 -- --strict` | ✅ 24 PASS / 0 GAP / 0 FAIL |
| vps pytest | `cd vps && pytest -q` | ✅ 98 passed |

## 8. 回顾（Retrospective）

### 8.1 做得好的

1. **按依赖顺序合并**：先 0912（摘要）再 0909/0913（抓取 + 快照），随后 0910/0911/0914/0915/0916，每次合并后立即跑 pytest + typecheck，问题在当次暴露；
2. **能力超集合并**：`trending_crawler.py` 同时保留 0913 的多页抓取与 0910 的重试诊断；`trending.py` 同时保留列表、快照、告警、详情、保留接口；
3. **验收脚本可复跑**：零第三方依赖，自动选端口、临时 D1、种子数据与报告输出，后续回归成本低；
4. **契约测试前移**：`test:trending` 的 11 个纯函数用例在合并前就锁定了查询解析、趋势计算与摘要回退。

### 8.2 集成暴露的问题（已修复）

| 问题 | 影响 | 修复 |
| --- | --- | --- |
| `0007` 与 `0008` 迁移重复 `ALTER TABLE ... ADD COLUMN readme_summary` | 本地 D1 全量迁移失败，M2 验收无法启动 | 移除 `0008` 的重复加列，仅保留索引 |
| `schemas.py` 重复定义 `TrendingRepoDetail` | 后者覆盖前者，字段契约不稳定 | 合并为单一定义，保留 `summary` / `summary_source` |
| `edge/src/trending/detail.ts` 未补 `TrendingRepo` 扩展字段 | edge typecheck 失败 | 补 `snapshotDate` / `rank` / `rankChange` / `trend` 中性默认值 |
| admin `api.ts` 缺少函数闭合括号、mock 详情缺趋势字段 | admin lint / tsc 失败 | 补 `}` 与 4 个必填字段；详情测试 fixture 同步 |
| 多分支同时改 `docs/*` / `vps/README.md` | 8 处文档冲突 | 逐处合并为能力超集，保留 0912/0916 两套计划入口 |

### 8.3 经验与改进

1. **迁移文件必须全局唯一编号并检查重复列**：并行分支各自 `ALTER TABLE` 同一列是高风险模式，后续应在合并清单里增加「迁移 diff 对照」步骤；
2. **共享 DTO 扩展要同步所有构造点**：`TrendingRepo` 加字段后，`detail.ts`、admin mock、测试 fixture 三处都要补，建议用类型工厂统一构造；
3. **验收脚本应尽早写**：本次脚本在合并完成后才写，若提前到第一轮合并就能更早发现迁移重复问题；
4. **VPS 与 edge 的验收边界要写清**：抓取 / 归档在 VPS，展示 / 回写在 edge，报告按能力归属分别引用证据，避免「脚本没测到 = 没验收」。

### 8.4 遗留与后续

1. **M2-09 Gitee**：Q2 已确认本期不接入；后续如需恢复，可复用 `crawl_gitee_explore` 与多页抓取框架；
2. **真实凭据联调**：GitHub Trending 线上抓取、Cloudflare D1 远端迁移、VPS 生产部署需人工凭据；
3. **归档恢复演练**：M2-08 已有 gzip JSONL 归档，但尚未做「从归档恢复」的演练，建议纳入 M5 备份恢复；
4. **质量抽检闭环**：M2-04 的人工复核 API 已就绪，admin 侧复核页面可在 M3 前补做。

## 9. 复跑方式

```bash
cd edge
npm run test:m2 -- --strict \
  --report-md docs/planning/acceptance-m2-report.md \
  --report-json docs/planning/acceptance-m2-report.json
```

脚本自动选择空闲端口、创建临时 D1 目录并在结束时清理；`--keep` 可保留 D1 目录用于排查。
