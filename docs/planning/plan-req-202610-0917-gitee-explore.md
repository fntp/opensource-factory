# 实施计划 · REQ-202610-0917 Gitee 探索页抓取（Q2 确认）

> 需求：REQ-202610-0917（backlog M2-09）｜ 分支：`feat/req-202610-0917-gitee-explore`
> 结论：2026-10-22 经决策面板确认，**本期不接入 Gitee 抓取**（Q2 维持 A + B），本需求按决策收口。

## 1. 需求与依赖

- 需求标题：Gitee 探索页抓取（待 Q2 确认）；
- 依赖：Q2「Gitee 相关能力是否本期接入」；
- 现状备注：预留入口已存在（`vps/app/services/trending_crawler.py::crawl_gitee_explore`，`crawl_trending` 支持 `platform=gitee|all`）。

## 2. 现状盘点

- `trending_repositories.platform` 已预留 `'gitee'`（D1 迁移与本地模型一致）；
- `crawl_gitee_explore()` 为「尽力而为」实现：多组候选选择器、单卡片失败隔离、网络失败返回空列表；
- `jobs.crawl_trending(platform=...)` 支持手动触发 Gitee 抓取，但 beat 默认仅 `platform=github`；
- 现有入口无独立离线单测，页面结构变化时只能依赖日志排查。

## 3. 可行性验证（2026-10-22）

| 检查 | 结果 |
| --- | --- |
| `GET https://gitee.com/explore`（本机出口，浏览器 UA） | HTTP 405，返回 JS 反爬挑战页（`nox` / `gangplank`），无可解析的仓库卡片 HTML |
| `GET https://gitee.com/api/v5/search/repositories?q=vue&sort=stars_count` | HTTP 200，但匿名调用返回空数组 |

结论：即使本期接入，也需要 Cookie / 代理 / 官方授权等额外条件；应先做数据获取可行性验证，再投入解析器与调度开发。

## 4. 决策与范围

- **决策**：本期不接入（决策面板选项 `defer`，2026-10-22，确认人 fntp）；
- **代码**：不修改抓取逻辑，保留 `platform='gitee'` 字段、`crawl_gitee_explore()` 预留入口与手动触发参数；
- **文档**：
  - `docs/requirements/open-questions.md`：Q2 标记已确认，记录结论与技术备注；
  - `docs/requirements/backlog.md`：M2-09 更新为「Q2 已确认：本期不接入」；
  - `docs/requirements/spec.md`：模块二增加 Q2 范围说明；
  - `docs/integration/reference-projects.md`、`vps/README.md`：同步预留入口口径；
  - `docs/planning/task-planning.md`：变更历史登记本次决策。

## 5. 验证

- 文档一致性：`git diff --check`；
- 无代码改动，不涉及 edge / admin 构建；`vps` 既有测试作为基线回归（如环境可用）。

## 6. 后续建议

重新评估 Gitee 能力时，按以下顺序推进：

1. 先解决数据获取：评估官方 OpenAPI 授权、Cookie 会话或合规代理，确认稳定可用的数据源；
2. 再补解析器：以真实页面 / 接口样例做 fixture，覆盖卡片结构变化与字段缺失；
3. 最后接调度：新增 `GITEE_ENABLED` 开关（默认关闭）与独立 beat 配置，避免影响 GitHub 主链路；
4. 同步更新 Q2 结论与 M2-09 状态。
