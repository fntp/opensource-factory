# 任务规划（路线图）· Roadmap

> 文档编号：PL-01 ｜ 维护人：fntp ｜ 更新方式：里程碑状态变化时更新

## 里程碑总览

| 里程碑 | 主题 | 范围 | 状态 |
| --- | --- | --- | --- |
| M0 | **项目立项** | 规范 / 文档 / 基建 / UI 骨架 / 参考项目集成 | ✅ 已完成（REQ-202610-0454） |
| M1 | 资产同步闭环 | GitHub OAuth 打通、增量同步 Starred/自有仓库、分类树 + 标签、秒级检索 | ⏳ 规划中 |
| M2 | 热榜与摘要 | GitHub Trending 定时抓取、README 清洗与摘要、热榜页联动 | ⏳ 规划中 |
| M3 | 推荐引擎 | BGE-M3 向量化、Vectorize 同步、RAG 语义匹配、推荐页闭环 | ⏳ 规划中 |
| M4 | 定向推送 | 每日评估、通知中心、Bark / Telegram / Email 通道 | ⏳ 规划中 |
| M5 | 上线硬化 | 域名 / 部署 / 监控、权限与限流、数据备份 | ⏳ 规划中 |

## M0 · 项目立项（本次交付）

**目标**：把「空地」变成可持续开发的工程基座。

- [x] 规范落实：项目 / 代码约束 / 需求 / 编码 四份规范（`docs/standards/`）
- [x] 文档落实：Agent 维护文档、任务规划、计划文档、开发周期（`docs/guides/` + `docs/planning/`）
- [x] 文档管理：`docs/` 统一存放全部文档与数据资产
- [x] 功能集成：参考项目能力移植（bookmark-recommender → vps/edge；shadcn-admin → admin）
- [x] UI 风格延续 shadcn-admin 模板（组件体系、布局、主题、配置抽屉原样保留）
- [x] 鉴权配置：仅 GitHub 授权登录（演示模式兜底）
- [x] 实施步骤：需求梳理 → 项目基建 → UI 落地

## M1 · 资产同步闭环

- [ ] GitHub OAuth 全链路联调（edge ↔ GitHub，会话持久化）
- [ ] 同步任务：Starred + 个人仓库增量拉取（vps Celery）
- [ ] 分类树（无限级）与标签体系 CRUD
- [ ] 组合筛选与秒级检索（D1 索引优化）
- [ ] admin 页面联调（替换演示数据）

## M2 · 热榜与摘要

- [ ] GitHub Trending 每日定时抓取（Celery beat）
- [ ] README 清洗 + 中文摘要（Ollama，DeepSeek 降级）
- [ ] 热榜页：日期 / 语言筛选、趋势标注

## M3 · 推荐引擎

- [ ] BGE-M3 向量化管线（本地）
- [ ] Vectorize 索引同步（edge）
- [ ] 自然语言语义匹配（RAG）
- [ ] 推荐结果解释（reason 生成）

## M4 · 定向推送

- [ ] 每日评估任务（质量分 + 匹配度阈值）
- [ ] 通知中心（站内）
- [ ] Bark / Telegram / Email 通道（按用户配置）

## M5 · 上线硬化

- [ ] 自定义域名 + HTTPS、Cloudflare Pages / Workers 正式部署
- [ ] 监控告警（Workers Analytics + VPS 日志）
- [ ] 备份与恢复演练（D1 导出、VPS 数据快照）
