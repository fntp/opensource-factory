# 实施计划 · REQ-202610-0949 相似项目推荐（向量近邻「看了又看」）

> 需求：REQ-202610-0949（backlog M6-02）｜ 分支：`feat/req-202610-0949-similar-recommendations`
> 依赖：M3-03 Vectorize 索引同步（REQ-202610-0921）
> 目标：以仓库自身向量为查询向量，检索语义近邻项目，在热榜详情页提供「看了又看」区块，
> 同时为收藏库 / 热榜提供统一的相似项目 API。

## 1. 现状与缺口

- M3-02 已把收藏库与热榜写入 `repo_vectors`，M3-03 已把同一批向量同步到 Vectorize；
- M3-04 的语义搜索只能从「自然语言查询」出发，不能以某个仓库为种子找邻居；
- 热榜详情页已有摘要、元信息与收藏动作，但没有「相似项目」出口，用户看完一个项目后缺少继续浏览路径；
- 相似推荐需要排除种子自身、跨模型 / 跨维度向量，并在向量缺失时给出可解释的降级结果。

## 2. 方案总览

```
admin 热榜详情页
  → GET /api/similar?source=trending&repoId=owner/name&topK=8&scope=all
       ↓ edge（登录态可选；my 来源必须登录并校验归属）
       ├─ 1. 调 VPS POST /api/search/similar（X-Internal-Token）
       │      → 读取种子向量 → repo_vectors 余弦近邻（mode=local）
       │      → 返回 source/repoId/score 命中（不水合，避免越权）
       ├─ 2. VPS 不可达 / 无命中 → D1 同语言 + 技术栈兜底（mode=keyword）
       └─ 3. edge 按当前用户水合 my 行（trending 全局）→ 返回完整项目卡片
```

设计要点：

- **种子向量即查询向量**：不做额外编码，保证「看了又看」与语义搜索共用同一向量空间；
- **严格同模型 / 同维度**：只比较 `model + dim` 一致的向量，避免跨模型余弦失真；
- **权限在 edge**：VPS 本地镜像不承担多租户隔离；edge 水合时 `my` 只保留当前用户的行；
- **降级可解释**：向量缺失 / VPS 不可达时回退同语言 + 技术栈匹配，响应标注 `mode=keyword`；
- **默认排除自身**，可选 `excludeSaved=true` 排除收藏库（避免推荐用户已经收藏的项目）。

## 3. 接口

| 端点 | 方法 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| `/api/similar` | GET | 登录可选（`source=my` 必须登录） | 相似项目推荐；`source` / `repoId` / `topK` / `scope` / `minScore` / `excludeSaved` |
| `/api/search/similar` | POST | `X-Internal-Token` | VPS 本地向量近邻（未水合），供 edge 调用与调试 |

响应（edge）：

```json
{
  "source": "trending",
  "repoId": "langchain-ai/langchain",
  "mode": "local",
  "count": 8,
  "tookMs": 12,
  "items": [
    {
      "id": "microsoft/autogen",
      "source": "trending",
      "fullName": "microsoft/autogen",
      "name": "autogen",
      "description": "面向多智能体应用的编程框架",
      "language": "Python",
      "stars": 38000,
      "starsToday": 402,
      "url": "https://github.com/microsoft/autogen",
      "score": 0.87,
      "reason": "与「langchain」语义相似度 87%。主要使用 Python 开发；……"
    }
  ]
}
```

## 4. 交付物

| 文件 | 说明 |
| --- | --- |
| `vps/app/services/similar_recommendations.py` | 种子向量读取、同模型近邻检索、排除自身 / 收藏库、水合 |
| `vps/app/api/search.py` | 新增 `POST /api/search/similar` |
| `vps/app/schemas.py` | `SimilarQuery` / `SimilarSeedOut` / `SimilarQueryResponse` |
| `vps/tests/test_similar_recommendations.py` | 纯函数、排除规则、维度 / 模型过滤、API 与鉴权 |
| `edge/src/search/items.ts` | 抽取搜索 / 相似推荐共用的水合逻辑 |
| `edge/src/similar/helpers.ts` | 参数归一化、理由文案、关键词兜底打分 |
| `edge/src/routes/similar.ts` | `GET /api/similar`，local → keyword 降级 |
| `edge/scripts/similar-helpers.test.mjs` | 参数归一化、理由与兜底打分纯函数测试 |
| `admin/src/features/trending/api.ts` | 相似推荐 DTO、请求封装与演示数据 |
| `admin/src/features/trending/detail-page.tsx` | 详情页「看了又看」区块 |
| `admin/src/features/trending/similar.test.ts` | 路径拼接与演示兜底测试 |
| `docs/architecture/overview.md` | 相似推荐流与接口清单 |
| `docs/requirements/backlog.md` / `roadmap.md` / `task-planning.md` | M6-02 状态与交付记录 |
| `docs/README.md` / 三端 README | 文档索引与模块说明 |

## 5. 测试与验收

| 层 | 用例 |
| --- | --- |
| vps | 种子缺失 / 未向量化、排除自身、`excludeSaved`、模型 / 维度不一致跳过、minScore、topK、水合、API 鉴权 |
| edge | `normalizeSimilarSource` / `clampSimilarTopK` / `fallbackReason` / `fallbackScore` 纯函数；`npm run typecheck` |
| admin | `similarReposPath`、演示数据过滤与排序；lint / build / Vitest |
| 手工 | 有向量时详情页出现「看了又看」；无向量时走关键词兜底且不报错 |

验收标准：

1. 给定 `source + repoId` 能返回按余弦相似度降序的近邻，且不包含种子自身；
2. 跨模型 / 跨维度向量不会参与比较，不产生错误分数；
3. `source=my` 未登录返回 401，且不会返回其他用户收藏；
4. VPS 不可达 / 种子未向量化时，edge 返回同语言 / 技术栈兜底结果，页面不空白；
5. 热榜详情页展示「看了又看」，点击可进入相似项目详情；
6. vps pytest、edge typecheck / test、admin lint / build / test 全绿。

## 6. 风险与后续

- **向量覆盖率**：新抓取项目在向量化任务完成前没有种子向量，只能走关键词兜底；后续可在详情页提示「等待向量化」；
- **单机全量扫描**：本地余弦为 O(候选数 × 维度)，当前 `SEARCH_MAX_VECTORS` 上限 50000；规模增长后应切换到 Vectorize 近邻；
- **模型升级**：更换 `EMBEDDING_MODEL` 后旧向量与新种子模型不一致会被跳过，需重跑向量化；
- **点击反馈**：本期只展示相似项目，不记录「看了又看」点击；后续可接入推荐反馈表形成闭环。
