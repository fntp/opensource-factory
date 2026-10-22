# 计划文档 · Task Planning

> 文档编号：PL-02 ｜ 维护人：fntp ｜ 更新方式：任务状态变化时更新
>
> 迭代计数：`IT-XXXX` 全局递增（IT-0001 起）。已发生：IT-0001 = REQ-202610-0454（立项）、IT-0002 = REQ-202610-0462（规划，本迭代）。

## 已完成迭代：IT-0001 / REQ-202610-0454（项目立项）

| # | 任务 | 产出 | 状态 |
| --- | --- | --- | --- |
| 1 | 梳理需求（8 条立项要求 → 功能点） | `docs/requirements/feature-analysis.md` | ✅ |
| 2 | 规范落实（4 份规范） | `docs/standards/*` | ✅ |
| 3 | 文档落实（维护 / 规划 / 计划 / 周期） | `docs/guides/*`、`docs/planning/*` | ✅ |
| 4 | 文档管理（docs 目录与数据资产） | `docs/README.md`、`docs/assets/d1-schema.sql` | ✅ |
| 5 | 项目基建（monorepo：admin / edge / vps） | 三端骨架 + CI | ✅ |
| 6 | UI 落地（延续 shadcn-admin 风格） | admin 页面：登录 / 仪表盘 / 仓库 / 分类 / 热榜 / 推荐 | ✅ |
| 7 | 功能集成（参考项目能力移植） | vps services、edge 路由、admin 演示数据 | ✅ |
| 8 | 鉴权配置（仅 GitHub 登录） | edge `/api/auth/*` + admin 登录页 | ✅ |
| 9 | 检查与交付（lint / build / test） | 验证记录 + 提交 + 回报 | ✅ |
| 10 | 待确认问题整理 | `docs/requirements/open-questions.md` | ✅ |

## 当前迭代：IT-0002 / REQ-202610-0462（需求调研与完整规划）

| # | 任务 | 产出 | 状态 |
| --- | --- | --- | --- |
| 1 | 现状盘点与需求调研 | 本文件 + `requirements/backlog.md` §1 | ✅ |
| 2 | 完整路线图扩展（M6–M9、常设轨道、迭代预算） | `planning/roadmap.md` | ✅ |
| 3 | 需求池回填（需求列表，92 条 + 常设轨道） | `requirements/backlog.md` | ✅ |
| 4 | 资源规划（4G / 15G、部署与保密） | `planning/resource-plan.md` | ✅ |
| 5 | 后续迭代排期 | 本文件「后续迭代排期」 | ✅ |
| 6 | 文档同步（索引 / 周期 / 待确认问题） | `docs/README.md`、`guides/dev-cycle.md`、`requirements/open-questions.md` | ✅ |
| 7 | 检查与交付（三端检查 + 推送 + 回报） | 验证记录 + 提交哈希 | ✅ |

## 后续迭代排期（近期）

> 完整需求池见 `requirements/backlog.md`；本表按依赖给出最近 10 个迭代的排期建议，随进展滚动更新。

| 迭代 | 需求 | 内容 | 依赖 | 状态 |
| --- | --- | --- | --- | --- |
| IT-0003 | M1-01 | 本机运行环境与部署基线（目录 / Redis / 进程管理） | 本机资源就绪 | ✅ 已完成（2026-10-22） |
| IT-0004 | M1-02 | D1 创建与迁移应用（先本地模式验证） | 人工：Cloudflare（Q3） | 待排期 |
| IT-0005 | M1-03 | GitHub OAuth 注册与登录联调（先本地回调） | 人工：OAuth App（Q3） | 待排期 |
| IT-0006 | M1-05 | Starred 全量同步 | IT-0003~0005 | 待排期 |
| IT-0007 | M1-07 | 增量同步策略 | IT-0006 | 待排期 |
| IT-0008 | M1-09 | 分类树 CRUD | IT-0004 | ✅ 已完成（2026-10-22，REQ-202610-0901） |
| IT-0009 | M1-10 | 标签体系 CRUD | IT-0004 | 待排期 |
| IT-0010 | M1-11/12 | 组合筛选与秒级检索优化 | IT-0006/0008/0009 | 待排期 |
| IT-0011 | M1-13 | README 摘要接入（Ollama 降级链 + 批量队列，2G 预算内） | IT-0006；M3-01 前置 | ✅ 已完成（2026-10-22） |
| IT-0012 | M1-14/15 | admin 真实接口联调 + M1 验收 | IT-0006~0011 | 待排期 |
| IT-0013 | M2-04 | 中文摘要批量生成（多来源 + 质量抽检 / 人工复核） | IT-0011 | ✅ 已完成（2026-10-22） |
| IT-0014 | M2-01~03/05~10 | 热榜抓取、快照、筛选、详情、保留与 M2 验收 | IT-0011/0013 | ✅ 已完成（2026-10-22） |
| IT-0015 | M3-01 | 模型选型与 2G 预算验证（bge-m3 int8 + ≤2B LLM） | — | ✅ 已完成（2026-10-22） |
| IT-0016 | M3-02 | 向量化管线（收藏库 + 热榜；批量 / 增量 / 断点续跑） | IT-0015 | ✅ 已完成（2026-10-22） |
| IT-0017 | M3-03 | Vectorize 索引同步（批量 upsert / 失败重试 / 对账） | IT-0016、Q3 | ✅ 已完成（2026-10-22） |
| IT-0018 | M3-04 | 语义搜索接口与页面（自然语言检索） | IT-0017 | ✅ 已完成（2026-10-22） |
| IT-0019 | M3-05 | 每日推荐生成任务（阈值 / 去重已收藏 / 打分） | IT-0016 | ✅ 已完成（2026-10-22） |
| IT-0020 | M3-06 | 推荐理由生成（画像感知中文理由 + `based_on` 依据字段） | IT-0019 | ✅ 已完成（2026-10-22） |
| IT-0021 | M3-07 | 推荐页闭环（收藏 / 忽略 / 点击反馈回流） | IT-0019/0020 | ✅ 已完成（2026-10-22） |
| IT-0022 | M3-08 | 推荐质量评估与阈值调参（抽样评估集） | IT-0021 | ✅ 已完成（2026-10-22） |
| IT-0023 | M3-09 | 降级路径验证（模型缺失 / 超预算 → hash 向量 / 截断摘要） | IT-0016 | ✅ 已完成（2026-10-22） |
| IT-0024 | M3-10 | 查询理解增强（同义词 / 技术栈词表） | IT-0018 | ✅ 已完成（2026-10-22） |
| IT-0025 | M3-11 | M3 验收与回顾（集成 M3-01~10 + 跨分支 E2E） | IT-0015~0024 | ✅ 已完成（2026-10-22） |
| IT-0026 | M4-01 | 每日评估任务（质量分 + 匹配度阈值） | M3-05 | ✅ 已完成（2026-10-22） |
| IT-0027 | M4-02 | 站内通知中心（edge + admin） | M4-01 | ✅ 已完成（2026-10-22） |
| IT-0028 | M4-03 | Bark 通道（09:05 投递 / 幂等 / 失败重试 / dry-run） | M4-02 | ✅ 已完成（2026-10-22） |
| IT-0029 | M4-04 | Telegram 通道（每日摘要 / 分片 / 退避） | M4-02 | ✅ 已完成（2026-10-22） |
| IT-0030 | M4-05 | Email 通道（SMTP / 幂等送达记录） | M4-02 | ✅ 已完成（2026-10-22） |
| IT-0031 | M4-06 | 推送偏好设置（时间 / 阈值 / 通道开关） | M4-02 | ✅ 已完成（2026-10-22） |
| IT-0032 | M4-07 | 推送去重与静默策略 | M4-02 | ✅ 已完成（2026-10-22） |
| IT-0033 | M4-08 | 推送记录与回执（送达状态） | M4-03~05 | ✅ 已完成（2026-10-22） |
| IT-0034 | M4-09 | M4 验收与回顾 | M4-01~08 | 🔄 进行中 |
| IT-0035 | M5-01 | 正式部署（Pages / Workers + 本机节点 + 域名 HTTPS） | IT-0025；Q3 | 🟡 工具链就绪（待 Q3 凭据执行） |
| IT-0036 | M5-02 | 本机一体化部署模式评估与落地（LOCAL_MODE + admin 静态托管 + 只读 API） | Q9；M1-01 | ✅ 已完成（2026-10-22） |
| IT-0037 | M5-03 | 监控与告警（健康检查 / 资源监控 / 日志 / Workers Analytics） | IT-0035；M5-01 | ✅ 已完成（2026-10-22） |
| IT-0038 | M5-04 | 备份与恢复（SQLite 快照 / D1 导出 / 恢复演练 / 保留策略） | IT-0035；M5-01 | ✅ 已完成（2026-10-22） |
| IT-0039 | M5-05 | 接口限流与安全加固（限流 / 内部令牌轮换 / 登录防护） | IT-0035；M5-01 | ✅ 已完成（2026-10-22） |
| IT-0040 | M5-06 | 资源预算实测验证（4G / 15G 红线；超限优化） | IT-0037；M5-01~03 | ✅ 已完成（2026-10-22） |
| IT-0041 | M5-07 | 运维手册（部署 / 升级 / 回滚 / 故障处理 SOP） | IT-0035；M5-01 | ✅ 已完成（2026-10-22） |
| IT-0042 | M5-08 | 安全审计（依赖漏洞扫描 / 配置检查 / 隐私边界复核） | IT-0035；M5-01 | ✅ 已完成（2026-10-22） |
| IT-0043 | M5-09 | M5 验收与发布 v1.0（集成 M5-01~08 + 验收脚本 + `v1.0.0` 标签） | IT-0035~0042 | ✅ 已完成（2026-10-22） |
| IT-0044 | M6-01 | 全文检索（README 全文镜像 + SQLite FTS5 trigram + 短词 LIKE 回退） | IT-0025；M1-12 | ✅ 已完成（2026-10-22） |
| IT-0045 | M6-02 | 相似项目推荐（向量近邻「看了又看」，edge 降级 + admin 详情页） | IT-0017/0018 | ✅ 已完成（2026-10-22） |
| IT-0046 | M6-03 | 重复 / 相似项目检测与合并建议（VPS 规则 + 向量复核、edge 兜底、admin 页面、按用户忽略） | IT-0045 | ✅ 已完成（2026-10-22） |
| IT-0047 | M6-04 | 技术栈图谱视图（语言 / 框架聚合） | IT-0010；M1-11 | ✅ 已完成（2026-10-22） |
| IT-0048 | M6-05 | 项目健康度追踪（最后提交 / issue 活跃 / 归档标记） | M1-05 | ✅ 已完成（2026-10-22） |
| IT-0049 | M6-06 | License 识别与合规提示（GitHub 元数据 + README 兜底 / 合规总览） | M2-03 | ✅ 已完成（2026-10-22） |
| IT-0050 | M6-07 | 依赖分析（清单解析 / 依赖入库 / 技术栈关联，edge 代理 + admin 依赖分析页） | IT-0047 | ✅ 已完成（2026-10-22） |
| IT-0051 | M6-08 | 知识库导出（Markdown / JSON / Obsidian；只读聚合 + `openfactory.knowledge.v1`） | M9-04（格式基线先行） | ✅ 已完成（2026-10-22） |
| IT-0052 | M6-12 | M6 验收与回顾（集成 M6-01~08 + 跨分支验收脚本 + 缺口登记） | IT-0044~0051 | ✅ 已完成（2026-10-22） |
| IT-0054 | M7-01 | 自动打标建议（摘要规则提取 + 人工确认 + tags / repo_tags 落库） | IT-0027（M2-04） | ✅ 已完成（2026-10-22） |
| IT-0055 | M7-02 | 自动分类建议（18 条业务线规则 + 可解释建议 + 采纳写回分类） | IT-0010；M7-01 | ✅ 已完成（2026-10-22） |
| IT-0056 | M7-03 | 每周 / 月度精选报告（D1 聚合 + Cron 自动生成 + admin 报告归档页） | M4-01 | ✅ 已完成（2026-10-22） |
| IT-0057 | M7-04 | 收藏项目更新提醒（VPS Release/Tag 扫描 + 重大变更判定 + D1 `repo_updates` + admin 更新提醒页） | M1-07 | ✅ 已完成（2026-10-22） |
| IT-0058 | M7-05 | Star 趋势与洞察视图（快照只读聚合 / Top Movers / 语言贡献 / 确定性洞察） | M2-05 | ✅ 已完成（2026-10-22） |
| IT-0059 | M7-06 | 模型路由与升级（任务级模型选择 + 预算内升级建议 + admin `/model-routing`） | IT-0015；M3-01 | ✅ 已完成（2026-10-22） |
| IT-0060 | M7-07 | Rerank 精排（六路信号 + MMR 多样性 + 预览 / 应用 + admin 精排工作台） | IT-0019 | ✅ 已完成（2026-10-22） |
| IT-0061 | M7-08 | 个人数据微调评估（LoRA 可行性；预算与效果双评估） | M7-06 | ⏳ 待排期（平台 pending） |
| IT-0062 | M7-09 | Agent 工作流（自动整理 / 草稿生成） | M7-01~03 | ⏳ 待排期（平台 pending） |
| IT-0063 | M7-10 | M7 验收与回顾（集成 M7-01~07 + 跨分支验收脚本 + 缺口登记） | IT-0054~0062 | ✅ 已完成（2026-10-22） |
| IT-0064 | M8-04 | 快捷入口（Raycast / 快捷指令类）评估（6 平台加权评分 + M8-05 API 前置清单 + 报告 / 契约） | M8-05（契约基线先行） | ✅ 已完成（2026-10-22） |
| IT-0065 | M8-01 | PWA 与移动端适配（manifest / Service Worker / 离线页 / 安装引导 + 移动端底部导航） | M5-01 | ✅ 已完成（2026-10-22） |
| IT-0066 | M8-02 | 浏览器扩展（MV3 一键收藏 + edge 令牌接口 + admin 令牌管理页） | M5-05 | ✅ 已完成（2026-10-22） |
| IT-0067 | M8-03 | Telegram Bot 查询入口（webhook 命令查询 + D1 绑定 + admin 设置面板） | M4-04 | ✅ 已完成（2026-10-22） |
| IT-0068 | M8-05 | 开放 API（个人令牌） | M5-05 | ⏳ 待排期（平台 pending） |
| IT-0069 | M8-06 | CLI 工具（命令行查询 / 收藏） | IT-0068；M8-05 | ⏳ 待排期（平台 pending） |
| IT-0070 | M8-07 | 离线可用（PWA 缓存 + 本地数据） | M8-01 | ⏳ 待排期（平台 pending） |
| IT-0071 | M8-08 | M8 验收与回顾（集成 M8-01~04 + 跨分支验收脚本 + 缺口登记） | M8-01~07 | ✅ 已完成（2026-10-22） |
| IT-0072 | M9-06 | 数据保留与隐私策略落地（策略 / 导出 / 删除 / D1 + VPS 每日清理 / admin 隐私页） | M5-08 | ✅ 已完成（2026-10-22） |

> 说明：IT-0004 / IT-0005 在人工资源（Cloudflare 账号、OAuth App）就绪前，可先以 `wrangler --local` + 本地回调完成开发与验证；其余按需求池顺序滚动排期。

## 变更历史

| 日期 | 变更 | 说明 |
| --- | --- | --- |
| 2026-10-12 | 创建 | 立项迭代任务拆解 |
| 2026-10-13 | 完成 | 立项任务全部完成，遗留问题转入 open-questions |
| 2026-10-13 | 推送 | 需求分支 feat/req-202610-0454-init 已推送至 GitHub（凭据就绪后） |
| 2026-10-13 | 规划 | 按 REQ-202610-0462 完成完整规划：需求池回填（92 条）、路线图扩展（M6–M9 + 常设轨道）、资源规划、后续迭代排期 |
| 2026-10-13 | 交付 | IT-0002 交付完成：三端检查全绿（admin 73 用例 / edge tsc / vps 20 用例）、分支 feat/req-202610-0462-planning 已推送、平台回报已确认 |
| 2026-10-22 | 交付 | IT-0011 / REQ-202610-0905 完成：README 摘要接入同步流程（Ollama 降级链 + 批量队列 + D1 回写），vps 29 用例 / edge tsc / admin 73 用例全绿 |
| 2026-10-22 | 交付 | IT-0013 / REQ-202610-0912 完成：摘要批量生成扩展至热榜，新增启发式质量评分、确定性抽检、样本留存与人工复核 API；计划见 `planning/plan-req-202610-0912-summary-quality.md` |
| 2026-10-22 | M2-02 | 抓取容错与页面结构变更告警：有限重试、解析诊断、`crawl_alerts` / `crawl_page_stats` 与告警 API，vps 用例全绿 |
| 2026-10-22 | M2-03 | README 清洗强化：徽章 / 图片 / HTML 块 / 链接地址去除、HTML 实体与零宽字符处理、技术栈别名归并与 language/topics 加权；vps 用例全绿 |
| 2026-10-22 | 交付 | REQ-202610-0914 / M2-06 热榜页联动：按日快照（migration 0007）、日期 / 语言筛选、趋势标注；计划见 `planning/plan-req-202610-0914-trending-page.md` |
| 2026-10-22 | 交付 | M2-07 / REQ-202610-0915 热榜详情页：edge 详情 + 收藏接口、admin 详情路由与一键收藏、VPS 详情摘要回退、迁移 0008 与文档同步 |
| 2026-10-22 | M2-01/05 | 热榜每日多语言抓取与按日快照：全局页 + 12 语言页、去重、排名 / Star 增量 / 连续上榜、D1 批量回写（REQ-202610-0909/0913） |
| 2026-10-22 | 交付 | M2-08 / REQ-202610-0916 热榜数据保留：90 天窗口、gzip JSONL 归档、本地 + D1 清理、每日 04:17 beat 任务与运维接口 |
| 2026-10-22 | 验收 | M2-10 / REQ-202610-0918 M2 验收与回顾：集成 8 个分支、24 项断言全 PASS、P95 38.3ms；报告见 `planning/acceptance-m2.md` |
| 2026-10-22 | 交付 | IT-0015 / REQ-202610-0919 完成：默认模型切换为 bge-m3 int8 + `qwen2.5:1.5b-instruct-q4_K_M`，新增 `app.model_budget` 预算校验与部署自检；见 `planning/plan-req-202610-0919-model-selection.md` |
| 2026-10-22 | 交付 | M3-02 向量化管线完成（REQ-202610-0920）：收藏库 + 热榜、批量 / 增量 / 断点续跑；计划见 `plan-req-202610-0920-vector-pipeline.md` |
| 2026-10-22 | 交付 | M3-03 / REQ-202610-0921 完成：Vectorize 批量 upsert、失败重试、增量 / 全量同步、断点续跑与对账（含孤儿清理开关），VPS + edge 测试全绿 |
| 2026-10-22 | 交付 | IT-0018 / M3-04 完成（REQ-202610-0922）：语义搜索 API + admin 检索页，Vectorize → 本地向量 → 关键词三级降级；计划见 `planning/plan-req-202610-0922-semantic-search.md` |
| 2026-10-22 | 交付 | IT-0019 / M3-05 完成：每日推荐生成（阈值 / 去重已收藏 / 综合打分 / `expired` 状态）+ Celery beat 08:30；计划见 `plan-req-202610-0923-daily-recommendations.md` |
| 2026-10-22 | 交付 | IT-0020 / M3-06 完成（REQ-202610-0924）：画像感知中文理由 + `based_on`、存量回填任务；计划见 `plan-req-202610-0924-recommend-reason.md` |
| 2026-10-22 | 交付 | IT-0021 / M3-07 完成（REQ-202610-0925）：推荐收藏 / 忽略 / 点击反馈落库，VPS 生成前拉取反馈并排除、生成后回写 D1；计划见 `plan-req-202610-0925-recommend-feedback.md` |
| 2026-10-22 | 交付 | IT-0022 / M3-08 完成（REQ-202610-0926）：推荐质量评估（Precision@K / Recall / MRR / NDCG / 覆盖率 / 多样性）+ 阈值与权重扫描；计划见 `plan-req-202610-0926-quality-eval.md` |
| 2026-10-22 | 交付 | IT-0023 / M3-09 完成：模型缺失 / 超预算降级路径自检（hash 向量 / 截断摘要）+ CLI 与内部接口；计划见 `plan-req-202610-0927-degradation-verification.md` |
| 2026-10-22 | 交付 | IT-0024 / M3-10 完成（REQ-202610-0928）：同义词 / 技术栈词表扩展接入 VPS 搜索链路、edge 关键词兜底与 admin 查询理解标签；计划见 `plan-req-202610-0928-query-understanding.md` |
| 2026-10-22 | 验收 | IT-0025 / M3-11 完成（REQ-202610-0929）：集成 M3-01~10 十个分支，跨分支 E2E 23 项全 PASS；报告见 `acceptance-m3.md` / `acceptance-m3-report.md` |
| 2026-10-22 | 交付 | IT-0026 / M4-01 完成（REQ-202610-0930）：每日评估（质量分 = 仓库 × 0.7 + 理由 × 0.3，匹配度 / 质量分双门槛）+ Celery beat 08:45；计划见 `plan-req-202610-0930-daily-evaluation.md` |
| 2026-10-22 | 交付 | IT-0040 / M5-06 资源预算实测（REQ-202610-0944）：新增 `app.resource_budget` CLI 与 `deploy/scripts/resource-budget.sh`，按 4G / 15G 红线采集 systemd RSS、模型峰值与磁盘分项；发现运行配置残留 `qwen2.5:7b`（4700 MB）并切换至 1.5B 量化模型，复测内存 1359.2 / 4096 MB、磁盘 106.2 / 15360 MB PASS；见 `guides/resource-budget-verification.md` |
| 2026-10-22 | 交付 | IT-0041 / M5-07 运维手册（REQ-202610-0945）：新增 `guides/operations-runbook.md`（部署 / 升级 / 回滚 / 故障处理 / 备份恢复 / 密钥轮换 SOP）与只读诊断脚本 `deploy/scripts/ops-diagnose.sh`，配套完整性测试；见 `planning/plan-req-202610-0945-operations-runbook.md` |
| 2026-10-22 | 交付 | IT-0042 / M5-08 安全审计（REQ-202610-0946）：新增只读审计 CLI `vps/app/security_audit.py` + `deploy/scripts/security-audit.sh`（密钥 / 依赖 / 配置 / 响应头 / 隐私 11 项检查，支持 `--online` 与 `--strict` 门禁）；整改 Vitest dev 依赖漏洞、edge / VPS 安全响应头、CORS 安全默认；隐私边界清单与遗留风险见 `docs/guides/security-audit.md`；计划见 `plan-req-202610-0946-security-audit.md` |
| 2026-10-22 | 验收 | IT-0043 / M5-09 完成（REQ-202610-0947）：集成 M5-01~08 八个分支，M5 验收 29/29 PASS，三端检查全绿（vps 421 / edge 61 / admin 117），发布 `v1.0.0`；报告见 `acceptance-m5.md` / `acceptance-m5-report.md` |
| 2026-10-22 | 交付 | IT-0054 / M7-01 自动打标建议（REQ-202610-0960）：VPS 规则词表 + `POST /api/tag-suggestions/generate`，edge 建议表 / 列表 / 生成 / 采纳 / 忽略路由与 D1 迁移 `0013`，admin `/tag-suggestions` 分组确认页；计划见 `plan-req-202610-0960-auto-tagging.md` |
| 2026-10-22 | 交付 | IT-0028 / M6-01 全文检索（REQ-202610-0948）：VPS `repo_readmes` 全文镜像 + FTS5 trigram 触发器同步、全文 / 状态 / 重建 API、每日补索引任务；edge 全文代理与用户过滤、admin 全文 / 语义切换与命中片段；计划见 `plan-req-202610-0948-fulltext-search.md` |
| 2026-10-22 | 交付 | IT-0045 / M6-02 完成（REQ-202610-0949）：相似项目向量近邻接口 + edge local→keyword 降级 + admin 详情页「看了又看」；计划见 `plan-req-202610-0949-similar-recommendations.md` |
| 2026-10-22 | 交付 | IT-0046 / M6-03 完成（REQ-202610-0950）：VPS 重复检测（地址 / 名称 / 简介 / 向量复核 + 合并建议）、edge 扫描与按用户忽略（migration 0013）、admin 重复检测页；计划见 `plan-req-202610-0950-duplicate-detection.md` |
| 2026-10-22 | 交付 | IT-0047 / M6-04 技术栈图谱（REQ-202610-0951）：新增 edge `GET /api/tech-stack`（D1 只读聚合，语言归一 + 标签 / 简介启发式框架识别）与 admin `/tech-stack` 页面（KPI、SVG 径向关系图、语言条形榜、框架排行、组合洞察、空状态）；计划见 `planning/plan-req-202610-0951-tech-stack-graph.md` |
| 2026-10-22 | 交付 | IT-0048 / M6-05 项目健康度（REQ-202610-0952）：VPS 拉取 pushed_at / issue / 归档字段并计算健康度，每日任务 + 手动刷新回写 D1；edge 本地兜底计算与健康度接口；admin 仓库页汇总、筛选、徽章与刷新按钮；计划见 `planning/plan-req-202610-0952-repo-health-tracking.md` |
| 2026-10-22 | 交付 | IT-0049 / M6-06 License 合规（REQ-202610-0953）：VPS License 识别任务（GitHub API + README 兜底）与目录 / 提示服务；edge `/api/licenses/*` 与 D1 回写；admin 仓库 / 热榜 License 徽章与合规总览；计划见 `planning/plan-req-202610-0953-license-compliance.md` |
| 2026-10-22 | 交付 | IT-0050 / M6-07 依赖分析（REQ-202610-0954）：8 类依赖清单解析 + `repo_dependencies` / 扫描状态落库 + 技术栈关联聚合 + edge 用户级代理与本地降级 + admin「依赖分析」页；计划见 `planning/plan-req-202610-0954-dependency-analysis.md` |
| 2026-10-22 | 交付 | IT-0051 / M6-08 知识库导出（REQ-202610-0955）：知识库导出（Markdown / JSON / Obsidian），edge 只读聚合 + `openfactory.knowledge.v1` 格式规范 + admin 导出页；计划见 `planning/plan-req-202610-0955-knowledge-export.md`，格式见 `guides/knowledge-export.md` |
| 2026-10-22 | 验收 | IT-0052 / M6-12 完成（REQ-202610-0959）：集成 M6-01~08 八个分支，M6 验收 18/18 PASS、3 项平台 pending 缺口登记；三端检查全绿（vps 482 / edge 108 / admin 156）；报告见 `planning/acceptance-m6.md` / `acceptance-m6-report.md` |
| 2026-10-22 | 交付 | IT-0055 / M7-02 完成（REQ-202610-0961）：18 条业务线分类规则（VPS 纯函数 + edge 本地兜底）、可解释建议生成、edge 建议表与采纳写回（migration 0017）、admin 分类建议页；计划见 `plan-req-202610-0961-auto-classification.md` |
| 2026-10-22 | 交付 | IT-0056 / M7-03 精选报告（REQ-202610-0962）：新增 D1 `curated_reports`（migration 0018）、edge 纯函数报告生成 + 登录态 / 内部接口 + Cron 周报月报、admin `/reports` 归档与 Markdown 下载；计划见 `planning/plan-req-202610-0962-weekly-monthly-report.md` |
| 2026-10-22 | 交付 | IT-0057 / M7-04 收藏项目更新提醒（REQ-202610-0963）：VPS 每日扫描 GitHub Release / Tag（首次记基线、主版本跃迁与 breaking 关键词判定重大变更），回写 D1 `repo_updates`（migration 0019）并写入通知中心；admin `/updates` 支持统计、筛选、已读 / 忽略与立即扫描；计划见 `planning/plan-req-202610-0963-repo-update-reminders.md` |
| 2026-10-22 | 交付 | IT-0058 / M7-05 Star 趋势与洞察（REQ-202610-0964）：新增 edge `GET /api/star-trends`（trending_snapshots 只读聚合，`scope=my` 覆盖率）与 admin `/star-trends` 页面（KPI、SVG 面积图、Top Movers、语言贡献、新上榜、确定性洞察）；计划见 `planning/plan-req-202610-0964-star-trend-insights.md` |
| 2026-10-22 | 交付 | IT-0059 / M7-06 模型路由（REQ-202610-0965）：VPS `model_route_configs` + 四策略路由 / 升级建议 / 健康检查接口，摘要与向量化接入路由决策；edge 登录态代理；admin `/model-routing` 页面；计划见 `planning/plan-req-202610-0965-model-routing.md` |
| 2026-10-22 | 交付 | IT-0060 / M7-07 完成（REQ-202610-0966）：Rerank 精排（相关性 / 画像亲和 / 时效 / 动量 / 人气 / 健康度六路信号 + MMR 多样性），每日生成自动接入并落库精排明细；VPS 预览 / 应用 API、edge 代理与本地降级、admin「精排工作台」；计划见 `planning/plan-req-202610-0966-rerank.md` |
| 2026-10-22 | 验收 | IT-0063 / M7-10 完成（REQ-202610-0969）：集成 M7-01~07 七个分支，M7 验收 14/14 PASS、2 项平台 pending 缺口登记；三端检查全绿（vps 532 / edge 180 / admin 224）；报告见 `planning/acceptance-m7.md` / `acceptance-m7-report.md` |
| 2026-10-22 | 评估 | IT-0064 / M8-04 完成（REQ-202610-0973）：新增离线评估工具 `app.services.quick_entry_eval`（6 平台 × 8 维加权评分、M8-05 16 项 API 就绪度、分阶段路线），产出 `architecture/quick-entry-evaluation.md` 与 `assets/quick-entry-api-contract.json`；Raycast 4.10 首选、Apple 快捷指令 3.95 次选；M8-05 未落地前全部阻塞 |
| 2026-10-22 | 验收 | IT-0071 / M8-08 完成（REQ-202610-0977）：集成 M8-01~04 四个分支，M8 验收 13/13 PASS、M8-05~07 三项平台 pending 缺口登记；三端检查全绿；报告见 `planning/acceptance-m8.md` / `acceptance-m8-report.md` |
| 2026-10-22 | 交付 | IT-0072 / M9-06 完成（REQ-202610-0983）：隐私策略 / 个人数据导出 / 账号删除 / D1 与 VPS 每日保留清理 / admin `/settings/privacy`；见 `guides/privacy-retention.md` |
