# 实施计划 · REQ-202610-0956 多轮问答式检索

> 需求：REQ-202610-0956（backlog M6-09）｜ 分支：`feat/req-202610-0956-conversational-search`
> 依赖：M3-04 语义搜索（REQ-202610-0922）
> 目标：把「输入关键词找项目」升级为「用自然语言连续追问」：用户可以直接问
> 「我的收藏里有哪些支付相关项目？」，再追问「那 Rust 的呢？」「还有吗？」，系统在
> 同一会话内继承主题、语言、范围与已展示结果，给出带引用编号的答案与项目卡片。

## 1. 现状与缺口

- M3-04 已提供单轮语义搜索：`POST /api/search/semantic`，Vectorize → 本地向量 → D1 关键词三级降级；
- M3-10 已提供查询理解词表（技术栈 / 概念同义词），但只作用于单次查询，不保留上下文；
- 现有搜索页每次提问都是一次独立请求，无法回答「那 Rust 的呢」「还有吗」「只看我的收藏」这类追问；
- VPS `my_repositories` 是全局镜像、没有 `user_id`，用户隔离必须继续由 edge 按 D1 完成。

## 2. 方案总览

```
admin /search/chat
  → POST /api/search/chat { messages[], shownIds[], scope?, topK }
    → edge（登录态）
       ├─ 校验会话消息（≤20 条、每条 ≤500 字）
       ├─ 读取当前用户 my_repositories.id 列表（≤5000）
       ├─ 调 VPS POST /api/search/chat（X-Internal-Token）
       │    → 回放用户轮次解析上下文：主题 / 语言 / 范围 / 意图 / 分页
       │    → 关键词匹配（D1 镜像 + 查询理解扩展词）
       │    → 本地向量命中（repo_vectors，按 myRepoIds 过滤）
       │    → 合并、语言过滤、排除已展示、排序、分页
       │    → 生成答案、引用编号、facets、追问建议
       ├─ 按 D1 重新水合 my 结果（user_id 二次过滤）与 trending 结果
       └─ VPS 不可达 → edge 本地关键词检索 + 模板答案（mode=keyword）
  → 页面渲染对话气泡、答案、项目卡片与可点击追问建议
```

设计原则：

1. **上下文显式化**：会话历史由客户端携带，VPS 无状态回放；不新增会话表，避免迁移与清理成本；
2. **权限仍在 edge**：VPS 只接收 `myRepoIds` 白名单，edge 返回前再按 `user_id` 水合过滤；
3. **确定性答案**：不依赖 LLM / 网络，答案由模板生成，测试可稳定断言；后续可接 M7 模型路由；
4. **可解释**：每个项目带 `reason` 与 `[n]` 引用编号，答案中的数量、语言、范围均来自实际命中；
5. **优雅降级**：VPS 不可达时 edge 用 D1 关键词 + 本地上下文解析兜底，页面不空白。

## 3. 多轮规则

| 追问形态 | 示例 | 处理 |
| --- | --- | --- |
| 主题继承 | 「那 Rust 的呢？」 | 继承上一轮主题「支付」，覆盖语言为 Rust |
| 范围切换 | 「只看热榜」「回到我的收藏」 | 覆盖 scope，主题 / 语言继承 |
| 翻页 | 「还有吗？」「再找一些」 | 按 `shownIds` 排除已展示，继续取下一页 |
| 数量 | 「我的收藏里有多少支付项目？」 | 返回总数与 Top 3 名称 |
| 详情 | 「第一个怎么样？」 | 返回当前结果第一条的详情 |
| 对比 | 「收藏和热榜里的支付项目对比」 | 按来源统计数量并给出对比结论 |
| 新主题 | 「换个话题：推荐系统」 | 重置已展示与语言，按新主题检索 |

- 语言识别覆盖 Python / JavaScript / TypeScript / Go / Rust / Java / Kotlin / Swift / C++ / C# / Ruby / PHP / Scala / Dart / Elixir / Lua；
- 范围识别覆盖「我的收藏 / 我的仓库 / 已收藏」「热榜 / 趋势 / 榜单」「全部 / 所有来源」；
- 主题抽取会剔除范围词、语言词、疑问词与「相关 / 项目 / 帮我找」等填充词，剩余内容作为主题；
- `shownIds` 由 admin 汇总历史 assistant 消息中的项目 id，随每次请求发送。

## 4. 接口契约

### 4.1 VPS `POST /api/search/chat`（`X-Internal-Token`）

请求：

```json
{
  "messages": [
    { "role": "user", "content": "我的收藏里有哪些支付相关项目？" },
    { "role": "assistant", "content": "在你的收藏里找到 3 个……" },
    { "role": "user", "content": "那 Rust 的呢？" }
  ],
  "myRepoIds": ["owner/repo"],
  "shownIds": ["owner/old-result"],
  "topK": 8,
  "scope": "my"
}
```

响应：

| 字段 | 说明 |
| --- | --- |
| `question` / `answer` | 本轮问题与答案（答案含 `[n]` 引用） |
| `intent` | `list` / `count` / `more` / `detail` / `compare` |
| `scope` / `topic` / `language` | 解析后的上下文 |
| `filters` | `language` / `concepts` / `terms` |
| `count` / `total` | 本页条数 / 过滤后总数 |
| `items[]` | 项目卡片（含 `citation`、`score`、`reason`） |
| `facets` | `languages[]` / `sources[]` 分布 |
| `suggestions[]` | 下一轮可点击追问 |
| `mode` | `hybrid` / `vector` / `keyword` |
| `tookMs` / `turn` / `backend` / `model` | 观测字段 |

### 4.2 edge `POST /api/search/chat`（登录态）

- 入参与 VPS 基本一致，额外接受 `scope: "auto" | "my" | "trending" | "all"`；
- 未登录 401；消息非法 400；VPS 不可达时返回 `mode=keyword` 的本地结果。

## 5. 交付物

| 文件 | 说明 |
| --- | --- |
| `vps/app/services/conversation_search.py` | 上下文回放、主题 / 语言 / 范围解析、关键词 + 向量混合检索、答案与建议生成 |
| `vps/app/api/search.py` | 新增 `POST /api/search/chat` |
| `vps/app/schemas.py` | 会话消息、请求 / 响应模型 |
| `vps/tests/test_conversation_search.py` | 上下文、过滤、分页、答案与 API 契约用例 |
| `edge/src/search/chat.ts` | 轻量上下文解析 / 兜底答案 / 建议纯函数 |
| `edge/src/routes/search-chat.ts` | 登录态、D1 用户白名单、VPS 代理与水合、关键词兜底 |
| `edge/src/types.ts` / `edge/src/index.ts` | 响应类型与路由挂载 |
| `edge/scripts/search-chat.test.mjs` | 纯函数测试 |
| `admin/src/features/search/api.ts` | 会话 DTO、请求封装与演示数据 |
| `admin/src/features/search/chat-utils.ts` | 消息校验、历史裁剪、已展示 id 汇总、展示辅助 |
| `admin/src/features/search/chat.tsx` | 对话页：消息流、结果卡片、追问建议、范围切换 |
| `admin/src/routes/_authenticated/search/chat.tsx` | 文件式路由 |
| `admin/src/features/search/chat.test.ts` | 工具函数测试 |
| `admin/src/components/layout/data/sidebar-data.ts` | 「开源资产」新增「问答检索」入口 |
| 文档 | 架构总览、数据模型、backlog、roadmap、task-planning、open-questions、三端 README |

## 6. 测试与验收

| 层 | 用例 |
| --- | --- |
| vps | 消息校验、主题 / 语言 / 范围解析、追问继承、`myRepoIds` 白名单、语言过滤、`shownIds` 分页、数量 / 详情 / 对比答案、API 契约 |
| edge | `normalizeChatMessages` / `detectLanguage` / `detectScope` / `extractTopic` / `resolveChatTurn` / `buildFallbackAnswer` 纯函数；`npm run typecheck` |
| admin | `normalizeChatContent` / `historyForRequest` / `collectShownIds` / `formatChatTime`；lint / build / Vitest |
| 手工 | 打开 `/search/chat`，连续问「我的收藏里有哪些支付相关项目？」→「那 Rust 的呢？」→「还有吗？」；验证答案、引用、卡片与建议 |

验收标准：

1. 首轮「我的收藏里有哪些支付相关项目？」能返回收藏库中的支付项目并给出数量；
2. 追问「那 Rust 的呢？」继承主题、只保留 Rust 项目；
3. 「还有吗？」不再重复已展示项目，没有更多时明确提示；
4. 「只看热榜」能切换范围且保留主题；
5. `myRepoIds` 之外的项目不会出现在答案或卡片中；
6. VPS 不可达时页面仍能返回 D1 关键词结果与模板答案；
7. vps pytest、edge typecheck / test、admin lint / build / test 全绿。

## 7. 风险与后续

- **模板答案**：当前答案不使用生成式模型，表达较固定；后续可在 M7-01 模型路由就绪后把模板替换为 LLM 改写，保留引用与事实校验；
- **上下文长度**：客户端最多携带 20 条消息，超出截断；长会话的摘要压缩留待后续；
- **向量覆盖率**：新收藏在向量化前只能靠关键词命中，答案会标注 `mode=keyword`；
- **同名 / 通用词**：主题抽取对「工具」「平台」等泛词可能召回偏多，答案中会给出语言分布与总数，便于用户继续收窄；
- **会话不持久化**：刷新页面后历史丢失；如需要跨设备会话，再评估 D1 会话表与保留策略（登记 open-questions）。
