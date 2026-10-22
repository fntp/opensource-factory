# 实施计划 · REQ-202610-0950 重复 / 相似项目检测与合并建议

> 需求：REQ-202610-0950（backlog M6-03）｜ 分支：`feat/req-202610-0950-duplicate-detection`
> 依赖：M6-02 相似项目推荐（REQ-202610-0949）
> 目标：在收藏库与热榜中识别「同一个项目被重复收录 / 改名 / 镜像」的条目，
> 给出可解释的相似证据与字段级合并建议，并在控制台提供检测、查看与忽略入口。

## 1. 现状与缺口

- M6-02 已能以单个仓库向量为种子找语义近邻，但那是「推荐相似项目」，不是「识别重复条目」；
- 收藏库存在同一项目以不同大小写 / 不同 URL / `.git` 后缀 / 改名后重复收录的情况；
- 热榜与收藏库之间会重复出现同一个项目，用户难以判断该保留哪一条、哪些元数据更完整；
- 目前没有任何合并建议或误报忽略机制，检测结果无法沉淀为可执行动作。

## 2. 方案总览

```
admin「重复检测」页
  → POST /api/duplicates/scan { scope, minScore, nameThreshold }
       ↓ edge（登录态；按当前用户取 D1 my_repositories）
       ├─ 1. 本地 D1 名称 / URL 归一化检测（exact / name 兜底，VPS 不可用也可用）
       ├─ 2. 调 VPS POST /api/duplicates/scan（X-Internal-Token）
       │      → 仓库地址归一化 → 名称 / 简介 token 相似 → 向量余弦复核
       │      → 并查集聚类 → 选主条目 → 字段级合并建议
       ├─ 3. 合并本地与 VPS 结果、按当前用户水合、过滤已忽略项
       └─ 4. 返回簇列表（含置信度、证据、保留 / 合并建议）
  → POST /api/duplicates/dismiss（D1，按用户记录忽略）
```

设计要点：

- **重复 ≠ 相似**：只有「地址归一化一致 / 名称高度相似 / 简介高度相似 + 向量复核」才进入重复簇，
  避免把同一技术栈的不同项目误判为重复；
- **向量只做复核**：沿用 M6-02 的 `repo_vectors`（同 model + dim），向量分用于提升 / 降低置信度，
  不单独凭向量判重；
- **权限在 edge**：VPS 不承担多租户隔离，edge 只把当前用户的 `myRepoIds` 传给 VPS，
  并在返回前再次按 D1 用户过滤；
- **合并建议只读**：本期不自动删除 / 改写任何仓库，只输出保留项、合并项与字段建议，由用户人工执行；
- **可忽略**：D1 按 `user_id + clusterKey` 记录忽略，同一组重复项不再打扰；
- **优雅降级**：VPS 不可达时 edge 用 D1 名称 / URL 规则给出保守结果，页面不空白。

## 3. 检测规则

| 信号 | 规则 | 权重 / 阈值 |
| --- | --- | --- |
| 地址归一化 | `html_url` / `repo_id` 去协议、域名、`.git`、大小写、尾斜杠 | 完全一致 = 1.0 |
| 名称相似 | 归一化名称的 token Jaccard 与字符序列相似度取大 | 默认 ≥ 0.86 |
| 简介相似 | 中英文 token（中文 bigram）Jaccard | 默认 ≥ 0.75 |
| 向量复核 | 同 model + dim 的余弦相似度 | 默认 ≥ 0.88 |

- 同平台内比较（GitHub 与 Gitee 的同名项目视为不同平台条目，不直接合并）；
- 跨来源（my ↔ trending）允许成簇，建议优先保留收藏库条目；
- 名称命中的置信度 = 名称 0.7 + 简介 0.15 + 向量 0.15（无向量时用名称补位）；
  语义命中（名称不相似、向量复核通过）= 简介 0.45 + 向量 0.55；低于 `DUPLICATE_MIN_CONFIDENCE` 丢弃；
- 并查集合并两两命中，簇内取最高置信度；全局最多 50 个簇。

## 4. 数据与接口

### 4.1 D1（edge）

`duplicate_dismissals`（迁移 `0010_duplicate_dismissals.sql`）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `user_id` | TEXT | 用户 id |
| `cluster_key` | TEXT | 稳定的成员签名哈希 |
| `reason` | TEXT | 忽略原因（可空） |
| `created_at` | TEXT | ISO 时间 |
| 唯一索引 | `(user_id, cluster_key)` | 同一用户同一簇只记一次（`id` 为 UUID 主键） |

### 4.2 VPS

`POST /api/duplicates/scan`（`X-Internal-Token`）：

```json
{
  "scope": "all",
  "myRepoIds": ["owner/repo"],
  "minScore": 0.7,
  "nameThreshold": 0.86,
  "maxRepos": 500,
  "maxClusters": 50
}
```

响应包含 `scanId` / `scanned` / `compared` / `clusters[]` / `tookMs` / `thresholds`；
每个簇包含 `id`、`kind`、`confidence`、`reasons`、`members[]`、`suggestion`。

### 4.3 edge

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/duplicates/scan` | POST | 登录态；合并 D1 本地规则与 VPS 结果，过滤已忽略 |
| `/api/duplicates/dismiss` | POST | 记录忽略（`clusterId` / `repoIds` / `reason`） |
| `/api/duplicates/dismissed` | GET | 当前用户已忽略列表 |
| `/api/duplicates/dismiss/:key` | DELETE | 恢复某条忽略 |

## 5. 交付物

| 文件 | 说明 |
| --- | --- |
| `vps/app/services/duplicates.py` | 归一化、token 相似、向量复核、并查集聚类、合并建议 |
| `vps/app/api/duplicates.py` | 内部扫描接口 |
| `vps/app/schemas.py` | 扫描请求 / 响应模型 |
| `vps/tests/test_duplicates.py` | 归一化、聚类、过滤、建议与 API 用例 |
| `edge/src/duplicates/helpers.ts` | 归一化 / 本地兜底检测 / 簇合并纯函数 |
| `edge/src/routes/duplicates.ts` | 扫描、忽略、恢复路由 |
| `edge/migrations/0010_duplicate_dismissals.sql` | 用户级忽略表 |
| `edge/scripts/duplicates-helpers.test.mjs` | 纯函数测试 |
| `admin/src/features/duplicates/api.ts` | DTO、请求封装、演示数据与纯函数 |
| `admin/src/features/duplicates/index.tsx` | 检测页：扫描、簇卡片、成员对比、合并建议、忽略 |
| `admin/src/routes/_authenticated/duplicates/index.tsx` | 文件式路由 |
| `admin/src/features/duplicates/duplicates.test.ts` | 展示辅助函数测试 |
| 文档 | 架构总览、数据模型、D1 schema、backlog、roadmap、task-planning、三端 README |

## 6. 测试与验收

| 层 | 用例 |
| --- | --- |
| vps | 地址归一化（大小写 / `.git` / URL / Gitee）、名称 token、中文简介 bigram、exact / name / semantic 聚类、跨来源、myRepoIds 过滤、scope、阈值、maxClusters、合并字段建议、API 契约 |
| edge | `normalizeRepoKey` / `nameSimilarity` / `detectNameDuplicates` / `mergeDuplicateClusters` / `clusterSignature` 纯函数；`npm run typecheck` |
| admin | `formatConfidence` / `kindLabel` / `fieldLabel` / `scanSummary` 等展示辅助函数与 API 请求封装；lint / build / Vitest |
| 手工 | 打开「重复检测」页，扫描后能看到簇与合并建议；忽略后刷新不再出现；VPS 不可用时仍能显示名称级结果 |

验收标准：

1. 同一仓库的不同 URL / 大小写 / `.git` 写法能合并为 exact 簇；
2. 改名 / 分隔符差异（`tenant-admin` vs `tenant_admin`）能被识别为 name 簇；
3. 名称不同但简介高度相似且有向量复核的条目能被识别为 semantic 簇；
4. 不同技术栈、不同简介的项目不会误报；
5. `myRepoIds` 之外的用户仓库不会出现在结果中；
6. 合并建议给出保留项、合并项、字段来源与理由；
7. 忽略后同一簇不再返回，可恢复；
8. vps pytest、edge typecheck / test、admin lint / build / test 全绿。

## 7. 风险与后续

- **同名不同项目**：`awesome`、`docs` 等通用名可能误报；本期用简介相似度与向量复核降权，并在 UI 标注「需人工确认」；
- **向量覆盖率**：未向量化的仓库只能走名称 / 简介规则，置信度上限 0.85；
- **合并执行**：本期只给建议，不自动改 D1 / VPS；后续可在用户确认后实现「合并并归档」写操作；
- **规模**：单次扫描默认 500 个仓库、O(n²) 名称比较；个人库足够，热榜规模增长后需引入分桶或离线任务；
- **跨平台镜像**：GitHub / Gitee 同名项目不直接合并，避免误删平台侧条目，后续可增加「跨平台镜像」类型。
