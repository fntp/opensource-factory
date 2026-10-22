# 实施计划 · REQ-202610-0960 自动打标建议（基于摘要）

> 需求：REQ-202610-0960（backlog M7-01）｜ 分支：`feat/req-202610-0960-auto-tagging`
> 依赖：M2-04 中文摘要批量生成（REQ-202610-0912，已交付）｜ 基线：`feat/req-202610-0959-m6-acceptance` @ `237c8e1`
> 目标：从仓库的中文摘要中自动提取可解释的标签建议，用户在控制台逐条确认后一键写入 `tags` / `repo_tags`，
> 降低人工打标成本，同时保证建议可解释、可忽略、可回退。

## 1. 现状与缺口

- M2-04 已为收藏仓库与热榜生成中文摘要（`readme_summary`），摘要覆盖「核心功能 / 技术栈 / 适用场景」三要素；
- 标签体系（`tags` / `repo_tags`）已建模，但后台只能展示标签，没有任何「从摘要推导标签」的能力；
- 用户给仓库打标需要逐条手写，仓库量大时成本高、口径不一致；
- M7-02「自动分类建议」依赖本需求，需要先形成「摘要 → 结构化建议 → 人工确认 → 落库」的通用闭环；
- 现有 M6-04 技术栈图谱已有框架词表，但只做只读聚合，未产出可执行建议。

## 2. 方案总览

```
admin /tag-suggestions
  ├─ GET  /api/tag-suggestions            列表（按用户隔离，pending / accepted / dismissed）
  ├─ POST /api/tag-suggestions/generate   对当前用户有摘要的仓库批量生成建议
  ├─ POST /api/tag-suggestions/accept     采纳（写 tags / repo_tags）
  └─ POST /api/tag-suggestions/dismiss    忽略
        ↓
edge（登录态）
  ├─ 从 D1 取当前用户仓库（必须有 readme_summary）
  ├─ 调 VPS POST /api/tag-suggestions/generate（X-Internal-Token）
  │     └─ 规则词表：语言 / 框架 / 业务域 / 工程属性，词边界 + 中文关键词
  ├─ VPS 不可用时 edge 本地规则兜底（language + 摘要关键词）
  └─ 建议 upsert 到 D1 tag_suggestions（user_id + repo_id + 标签 唯一）
```

设计原则：

1. **基于摘要、可解释**：每条建议必须带 `score`、`reason` 与 `evidence`（摘要片段 / 语言字段），不输出黑盒结果；
2. **建议与执行分离**：生成只写 `tag_suggestions`，不直接改 `tags` / `repo_tags`；用户采纳后才落标签；
3. **账号隔离**：edge 所有 SQL 带 `user_id = ?`，采纳时再次校验仓库归属；
4. **优雅降级**：VPS 不可达时 edge 用本地规则生成，页面不空白；没有摘要的仓库跳过并提示；
5. **幂等**：同一用户 + 仓库 + 标签只保留一条建议；重复生成更新分数与理由，不覆盖已采纳 / 已忽略状态；
6. **不新增外部依赖**：规则词表纯本地，测试不访问网络。

## 3. 接口契约

### 3.1 VPS `POST /api/tag-suggestions/generate`（X-Internal-Token）

请求：

```json
{
  "repoIds": ["owner/repo"],
  "limit": 200,
  "perRepo": 6
}
```

响应：

```json
{
  "generatedAt": "2026-10-22T12:00:00.000Z",
  "scanned": 12,
  "suggested": 9,
  "skipped": 3,
  "items": [
    {
      "repoId": "owner/repo",
      "tags": [
        {
          "name": "AI/LLM",
          "category": "domain",
          "score": 0.78,
          "reason": "摘要命中「大模型」",
          "evidence": "……基于大模型构建的对话应用……"
        }
      ]
    }
  ]
}
```

规则：

- 只处理 `readme_summary` 非空的仓库；`repoIds` 为空时按 Star 降序取 `limit` 条；
- 语言字段命中优先，其次框架别名、业务域关键词、工程属性；
- 英文别名使用词边界（避免 `react` 命中 `reactive`），中文关键词使用包含匹配；
- 排除仓库已有标签（大小写不敏感），同一仓库最多 `perRepo` 条（1~10）。

### 3.2 edge

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/tag-suggestions` | GET | 登录态；`status=pending\|accepted\|dismissed\|all`、`repoId`、`limit`、`offset`；返回列表 + 汇总 |
| `/api/tag-suggestions/generate` | POST | 登录态；`{repoIds?, limit?, perRepo?}`；生成并 upsert，返回 `source`（vps/local）与统计 |
| `/api/tag-suggestions/accept` | POST | 登录态；`{ids?}` 或 `{repoId, tags?}`；写 `tags` / `repo_tags` 并把建议标记 accepted |
| `/api/tag-suggestions/dismiss` | POST | 登录态；`{ids, reason?}`；标记 dismissed，重复生成不再打扰 |

列表项 DTO：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 稳定 id（用户 + 仓库 + 标签哈希） |
| `repoId` / `repoName` / `repoUrl` | string | 仓库标识与地址 |
| `summary` | string | 摘要（用于人工判断） |
| `tagName` | string | 建议标签 |
| `category` | `language\|framework\|domain\|quality` | 建议类别 |
| `score` | number | 置信度 0~1 |
| `reason` / `evidence` | string | 命中理由与证据片段 |
| `status` | `pending\|accepted\|dismissed` | 状态 |

### 3.3 D1 表 `tag_suggestions`（迁移 `0013`）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | TEXT | 主键（稳定哈希） |
| `user_id` | TEXT | 用户 id |
| `repo_id` | TEXT | 仓库 `owner/repo` |
| `tag_name` | TEXT | 标签展示名 |
| `normalized_name` | TEXT | 归一化标签名（小写 / 去空白） |
| `category` | TEXT | 建议类别 |
| `score` | REAL | 置信度 |
| `reason` / `evidence` | TEXT | 理由 / 证据 |
| `status` | TEXT | pending / accepted / dismissed |
| `created_at` / `updated_at` | TEXT | 时间 |

唯一索引 `(user_id, repo_id, normalized_name)`；列表索引 `(user_id, status, updated_at DESC)`。

## 4. 交付物

| 文件 | 说明 |
| --- | --- |
| `vps/app/services/tag_suggestions.py` | 词表、文本归一化、词边界匹配、打分与建议构建（纯函数） |
| `vps/app/api/tag_suggestions.py` | 内部生成接口 |
| `vps/app/schemas.py` | 请求 / 响应模型 |
| `vps/app/main.py` | 挂载路由 |
| `vps/tests/test_tag_suggestions.py` | 规则 / 排序 / 排除已有标签 / 接口契约 |
| `edge/src/tag-suggestions/helpers.ts` | 归一化、稳定 id、合并、本地兜底规则 |
| `edge/src/routes/tag-suggestions.ts` | 列表 / 生成 / 采纳 / 忽略路由 |
| `edge/migrations/0013_tag_suggestions.sql` | D1 建议表 |
| `edge/scripts/tag-suggestions.test.mjs` | 纯函数测试 |
| `admin/src/features/tag-suggestions/api.ts` | DTO、请求封装、演示数据 |
| `admin/src/features/tag-suggestions/utils.ts` | 分组、汇总、格式化、排序 |
| `admin/src/features/tag-suggestions/index.tsx` | 建议页：汇总卡、生成、仓库分组、采纳 / 忽略 |
| `admin/src/features/tag-suggestions/tag-suggestions.test.ts` | 工具函数测试 |
| `admin/src/routes/_authenticated/tag-suggestions/index.tsx` | 文件式路由 |
| `admin/src/components/layout/data/sidebar-data.ts` | 「开源资产」新增「打标建议」 |
| 文档 | 本计划、架构总览、数据模型、D1 Schema、backlog / roadmap / task-planning、三端 README |

## 5. 测试与验收

| 层 | 用例 |
| --- | --- |
| vps | 语言 / 框架词边界 / 中文关键词 / 排除已有标签 / 分数排序 / perRepo 限制 / 无摘要跳过 / 接口鉴权与响应 |
| edge | `normalizeTagKey` / `hashSuggestionId` / `clampLimit` / 合并去重 / 本地兜底 / DTO |
| admin | 分数格式化 / 按仓库分组 / 汇总统计 / 演示数据 |
| 回归 | `vps .venv/bin/pytest -q`；`edge npm run typecheck && npm test`；`admin npm run lint && npm run build && npm run test` |

验收标准：

1. 登录用户访问 `/tag-suggestions` 能看到待确认建议、覆盖仓库数、平均置信度与已采纳数；
2. 点击「生成建议」后，有摘要的仓库出现 1~N 条标签建议，每条带理由与证据；
3. 采纳后标签写入 `tags` / `repo_tags`，仓库列表能看到新标签；重复采纳不重复计数；
4. 忽略后该建议不再出现在待确认列表，重复生成不覆盖忽略状态；
5. VPS 不可用时页面仍可通过本地规则生成建议；
6. 三端检查全绿，文档同步更新。

## 6. 风险与后续

- **词表覆盖**：规则词表覆盖常见语言 / 框架 / 业务域，长尾项目可能漏标；后续可接 LLM 打标或 GitHub topics 扩充；
- **摘要质量**：摘要缺失或为截断降级时建议质量下降；列表会展示摘要供人工判断，低置信度建议默认排在后面；
- **标签口径**：不同用户可能使用同义标签（如 `LLM` / `大模型`）；本期按词表规范名输出，后续可做标签合并（M1-10）；
- **建议噪声**：简介提及但未实际使用的技术可能误判；采用词边界 + 已有标签排除 + 置信度阈值，后续可加用户反馈学习；
- **规模**：单次生成默认 200 个仓库、每仓库 6 条，规则匹配为 O(仓库数 × 词表)，个人库规模可接受。
