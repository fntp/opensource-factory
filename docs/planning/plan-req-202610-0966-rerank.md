# REQ-202610-0966 · Rerank 精排（提升推荐质量）实施计划

- **需求**：M7-07 Rerank 精排（提升推荐质量），依赖 M3-05 每日推荐生成
- **分支**：`feat/req-202610-0966-rerank`（基于 M6 验收集成分支 `6d20e1a`）
- **目标**：在现有「相似度 + 热榜热度」粗排之后增加确定性的第二阶段精排，
  综合相关性、画像亲和、时效、动量、人气、健康度与多样性，输出可解释的排序结果，
  并保留精排前后的名次对比。

## 1. 现状与缺口

M3-05 的 `rank_candidates` 只使用余弦相似度与今日 star 增量，存在三个问题：

1. **信号单一**：收藏库语言 / 技术栈亲和、项目时效与健康度未参与排序；
2. **列表同质化**：同一语言 / 技术栈的候选容易连续霸榜，缺少多样性控制；
3. **不可解释**：只有总分，无法回答「为什么它排在前面」。

## 2. 方案

### 2.1 纯函数精排服务 `vps/app/services/rerank.py`

对每个候选计算 6 个归一化信号（0~1）：

| 信号 | 计算口径 |
| --- | --- |
| relevance 相关性 | 粗排综合分（相似度 × 权重 + 热度 × 权重） |
| affinity 画像亲和 | 候选语言 / 技术栈与收藏库画像（Top 语言 + Top 技术词）的覆盖率 |
| freshness 时效 | `pushed_at` 越近越高（180 天半衰期）；缺失时中性 0.5 |
| momentum 动量 | 今日新增 star 的对数归一化（与候选池最大值比较） |
| popularity 人气 | 总 star 的对数归一化（与候选池最大值比较） |
| health 健康度 | 已归档 / 禁用 → 0；有 `health_score` 直接用；否则按元数据完整度（简介 / 摘要 / License / 语言与技术栈） |

加权总分按权重和归一化。随后用 **MMR**（Maximal Marginal Relevance）做多样性重排：

```
mmr = λ × score - (1 - λ) × max(与已选条目的相似度)
```

相似度优先使用仓库向量余弦，缺失时回退到语言 / 技术栈 Jaccard。λ 默认 0.75，
即「质量优先、适度去重」。

输出每条推荐的：粗排分、精排分、精排前后名次、各信号值 / 贡献、中文理由、
多样性惩罚；以及整体指标（平均名次变化、多样性前后对比、语言覆盖率）。

### 2.2 接入每日推荐生成

`generate_for_user` 在粗排时取更大的候选池（`RERANK_POOL_SIZE`），精排后取 `top_k`：

- `recommendations.score` 写精排分（edge 列表排序直接生效）；
- 新增 `base_score` / `rerank_score` / `rerank_rank` / `rerank_detail` / `reranked_at`；
- 精排关闭（`RERANK_ENABLED=false`）时行为与 M3-05 完全一致。

### 2.3 对外接口

- VPS `POST /api/recommend/rerank/preview`：对指定用户已有推荐做精排预览，不落库；
- VPS `POST /api/recommend/rerank/apply`：按同一参数精排并落库；
- edge `POST /api/rerank/preview` / `POST /api/rerank/apply`：登录鉴权 + 代理 VPS，
  VPS 不可达时用 D1 现有字段做本地启发式精排（`mode=local`）；
- admin `/rerank`「精排工作台」：展示指标卡、精排前后名次、信号贡献与理由，
  支持调整权重预设并重新精排 / 应用。

### 2.4 数据与配置

- D1 migration `0020_rerank.sql`：`recommendations` 增加精排列与索引；
- `docs/assets/d1-schema.sql` 同步；
- VPS `config.py` / `runtime.py` / `.env.example` / `deploy/env/openfactory.env.example`
  增加 `RERANK_*` 配置；
- 内部推荐回写契约增加 `baseScore` / `rerankScore` / `rerankRank` / `rerankDetail`。

## 3. 交付清单

| 层 | 文件 |
| --- | --- |
| VPS | `services/rerank.py`、`services/recommendation_service.py`、`services/recommendation_feedback.py`、`models.py`、`db.py`、`config.py`、`runtime.py`、`schemas.py`、`api/recommend.py` |
| edge | `migrations/0020_rerank.sql`、`types.ts`、`recommend/feedback.ts`、`routes/recommend.ts`、`routes/internal-recommendations.ts`、`rerank/helpers.ts`、`routes/rerank.ts`、`index.ts` |
| admin | `features/rerank/{api.ts,utils.ts,index.tsx,*.test.ts}`、`routes/_authenticated/rerank/index.tsx`、`sidebar-data.ts` |
| 文档 | 本计划、架构总览、数据模型、需求池 M7-07、路线图、任务排期、文档索引、open-questions |

## 4. 验证

- `vps/.venv/bin/pytest -q`：新增 `test_rerank.py`（信号、MMR、指标、幂等、API）；
- `edge npm run typecheck && npm test`：新增 `rerank-helpers.test.mjs`；
- `admin npm run lint && npm run build && npm run test`：新增 `rerank.test.ts`；
- 全部重活经 `bacs-heavy` 执行，开跑前检查 load / 可用内存。

## 5. 风险与取舍

- **不做在线学习**：权重为静态配置，后续可由 M3-08 评估结果调参；
- **多样性不牺牲相关性**：MMR λ 默认 0.75，且只作用于精排池，不改变粗排阈值；
- **历史数据兼容**：旧推荐 `base_score` 为空时回退 `score`，精排详情为空时前端隐藏对比；
- **性能**：精排为纯内存计算，500 候选 × 128 维以内开销可忽略；不做额外模型调用。
