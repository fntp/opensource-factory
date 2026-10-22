# 待确认问题 · Open Questions

> 需求编号：REQ-202610-0454 ｜ 机制说明：本任务为自动执行场景，遇到不确定点不阻塞开发，按「默认处理」推进并在此记录，等待人工确认后调整。

## Q1. 参考项目 `github_trending` 无法访问

- **现象**：需求提供的参考项目 `github_trending` 仓库返回 404（无访问权限 / 已删除 / 地址有误），无法获取其实现；
- **选项**：
  - A. 重新提供仓库地址或访问权限（推荐优先）；
  - B. 使用本仓库自研的最小化 Trending 爬虫替代（**当前默认**，已实现于 `vps/app/services/trending_crawler.py`）；
  - C. 提供离线压缩包 / 代码片段。
- **默认处理**：采用 B，自研实现具备同等能力（GitHub Trending 抓取 + 解析 + 入库）；若后续获得原仓库，可在 M2 对齐替换。

## Q2. Gitee 相关能力是否本期接入

- **背景**：模块一原设计含 Gitee OAuth，但立项要求明确「只需要 GitHub 授权登录」；
- **选项**：A. 完全不做（**当前默认**）；B. 仅预留数据字段（`platform='gitee'` 已预留）；C. 后续迭代实现。
- **默认处理**：A + B 预留字段，接口与表结构不阻塞未来接入。

## Q3. Cloudflare 资源信息（部署前必须提供）

- **所需**：账号 ID、D1 数据库 `database_id`、Vectorize 索引名与维度（BGE-M3 为 1024 维）、目标域名；
- **现状**：`edge/wrangler.toml` 中为占位符 `REPLACE_WITH_D1_DATABASE_ID`；Vectorize 绑定已按默认值预置（索引名 `opensource-factory-vectors`、1024 维、cosine）；
- **默认处理**：本地开发用 `--local` 模拟；正式部署前替换 D1 id，并执行 `npx wrangler vectorize create opensource-factory-vectors --dimensions=1024 --metric=cosine`。若实际维度不同，同步调整 `vps/.env` 的 `VECTORIZE_INDEX_DIM`，否则同步任务会跳过维度不一致的向量并计数 `dimSkipped`。
- **补充（2026-10-22，REQ-202610-0939 / M5-01）**：正式部署工具链已就绪——`deploy/scripts/{preflight,render-config,deploy-edge,deploy-admin,deploy-vps,deploy-all,smoke-test,setup-https}.sh`、`deploy/env/deploy.env.example`、`deploy/templates/*`、`.github/workflows/deploy.yml`，操作手册见 `docs/guides/production-deployment.md`。仍需人工提供：Cloudflare 账号 ID + API Token、D1 `database_id`、Vectorize 索引、Pages 项目名、三端域名、GitHub OAuth App、VPS SSH 目标。填好 `deploy/env/deploy.env` 后执行 `deploy/scripts/deploy-all.sh` 即可上线。

## Q4. LLM 与 Embedding 的默认配置

- **结论（M3-01，2026-10-22）**：默认 `qwen2.5:1.5b-instruct-q4_K_M`（Ollama，约 1.3G）+ `BAAI/bge-m3` int8（约 1.1G），峰值驻留 ≤ 2G；
- **选项**：
  - A. Ollama 本地模型 + BGE-M3 本地向量（**当前默认**，零成本 / 隐私）；
  - B. DeepSeek 云端 API（需 key，效果更稳）；
  - C. 混合：本地优先，云端降级（代码已支持）。
- **默认处理**：A + C 的降级链（`summarizer.py` 已实现 Ollama → DeepSeek → 截断兜底）；预算校验见 `python -m app.model_budget check`。

## Q5. 通知渠道优先级

- **选项**：A. 站内通知中心优先，Bark 次之（**当前默认**）；B. Telegram 优先；C. Email 优先。
- **默认处理**：A（M4 实现，接口已在数据模型中预留 `recommendations.status`）。

## Q6. 演示模式是否保留至上线

- **背景**：admin 在未配置 `VITE_API_BASE_URL` 时自动进入演示模式（内置演示数据）；
- **选项**：A. 保留（便于演示与离线开发，**当前默认**）；B. 上线时强制关闭（构建期报错提示）。
- **默认处理**：A；上线时在部署文档中明确「必须配置 `VITE_API_BASE_URL` 且 `VITE_DEMO_MODE=false`」。

## Q7. 平台密钥 / 推送凭据问题（✅ 已解决）

- **现象**：本机执行环境通过平台（keyId 39）换取 git 推送凭据失败（平台侧提示「父密钥不是认证类型密钥」且一次性令牌已消耗），导致本迭代代码**可能无法推送到 GitHub**；
- **选项**：
  - A. 在平台密钥管理中按「GitHub App 模板」修正 keyId 39 的配置后，重新触发推送（推荐）；
  - B. 由维护者在本机配置可用的 git 凭据（如 SSH key / PAT）后手动推送需求分支；
  - C. 提供补丁包离线交付。
- **默认处理**：✅ 已解决（2026-10-13）：维护者提供 PAT 后，需求分支已推送至 GitHub（`feat/req-202610-0454-init`）。建议仍修复平台 keyId 39（按 GitHub App 模板录入），以便后续任务自动换取推送凭据。
- **补充（2026-10-13，REQ-202610-0462 执行）**：再次验证平台换取仍失败（同因：父密钥非「认证类型」密钥）；本迭代推送继续使用维护者 PAT（GIT_ASKPASS 注入，不入库、不回显）。keyId 39 修复仍待平台侧按 GitHub App 模板处理。
- **补充（2026-10-14，REQ-202610-0746 执行）**：再次验证仍失败（同因）；本轮推送继续使用维护者 PAT。keyId 39 修复仍待平台侧处理。

## Q8. 前端 i18n（国际化）范围

- **背景**：核心界面已中文化，设置页 / 错误页等继承自模板的内部页面仍为英文；
- **选项**：A. 后续迭代统一做 i18n（**当前默认**）；B. 立即全量翻译。
- **默认处理**：A；已翻译范围：登录、导航、仪表盘、仓库、分类、热榜、推荐、退出登录等核心链路。

## Q9. 「部署在本机」的口径与 Cloudflare 边缘去留（REQ-202610-0462 新增）

- **背景**：本需求明确「项目直接部署在本机、机器专用、私有配置仅存本机」；现行架构为 Cloudflare 边缘（免费外部）+ 本机算力节点；
- **选项**：
  - A. 混合架构：本机承担全部 AI / 数据 / 私有配置，Cloudflare 仅做无状态控制面（页面托管 / 鉴权代理），不占本机资源（**当前默认**，改动最小）；
  - B. 本机一体化：增加本地 API / 元数据层，完全脱离 Cloudflare 离线运行（M5-02 评估并落地，工作量中等）；
  - C. 其他：由维护者指定。
- **默认处理**：A 先行（本机已承载全部私有数据与推理）；**2026-10-22 更新：B 已完成评估与落地**
  （REQ-202610-0940）——`LOCAL_MODE=1` 即可由 `openfactory-api` 单进程托管 admin 与
  `/local/api/*` 只读接口，离线可用；默认仍保持 A（`LOCAL_MODE=0`），由维护者按需切换。
  首版只读，写操作 / OAuth / 通知仍走 edge；详见
  [local-allinone-deployment.md](../guides/local-allinone-deployment.md)。

## Q10. README 摘要模型与 edge 回写地址（REQ-202610-0905 新增）

- **背景**：M1-13 依赖 M3-01 的模型选型，但 M3-01 尚未完成；摘要任务还需要知道 edge Worker 地址才能把结果回写 D1；
- **选项**：
  - A. 摘要模型沿用 `OLLAMA_MODEL`（当前默认 `qwen2.5:7b`），M3-01 完成后再切 ≤2B 量化模型；`EDGE_BASE_URL` 留空时只写本地镜像（**当前默认**，不阻塞本需求）；
  - B. 本需求内直接切换默认模型为 `qwen2.5:1.5b-instruct` 并配置生产 edge 地址（需要 M3-01 的实测数据与人工确认）；
  - C. 其他：由维护者指定模型与地址。
- **默认处理**：A。`SUMMARY_BATCH_SIZE / SUMMARY_MAX_PER_RUN / SUMMARY_DELAY_MS / OLLAMA_KEEP_ALIVE` 已按 2G 预算给出保守默认值；正式联调时在 `vps/.env` 配置 `EDGE_BASE_URL` 与 `INTERNAL_TOKEN` 即可回写 D1。

## Q12. 向量化模型与 Vectorize 维度（REQ-202610-0920 新增）

- **背景**：M3-02 的本地向量管线按 `EMBEDDING_MODEL` 可配置；当前默认 `BAAI/bge-m3` 为 1024 维，
  未安装重型依赖时降级为 256 维确定性 hash。M3-01 模型选型尚未合并，M3-03 同步 Vectorize 前需确认索引维度；
- **选项**：
  - A. 按 M3-01 选定的量化 BGE-M3 统一 1024 维，Vectorize 索引按 1024 维创建（**推荐**）；
  - B. 切换其他模型 / 维度：需同步重建 Vectorize 索引，并用 `force=true` 全量重算本地向量；
- **默认处理**：A；管线以 `model + backend` 判断增量，模型或后端变化时自动重算，
  上线前用 `GET /api/vectors/stats` 核对 `byModel` 与 `dim`。

## Q13. 推荐阈值与单用户画像口径（REQ-202610-0923 新增）

- **背景**：M3-05 每日推荐默认 `RECOMMEND_MIN_SCORE=0.30`，该值基于 hash 兜底向量的相似度分布
  （相关项目约 0.45~0.77，不相关约 0~0.08）；BGE-M3 的分布可能不同。另 VPS 本地
  `my_repositories` 暂无 `user_id`，多用户场景下所有用户共用同一收藏画像；
- **选项**：
  - A. 先用默认 0.30 上线，M3-08 用抽样评估集校准阈值与权重（**当前默认**）；
  - B. 由维护者直接指定阈值 / 权重；
  - C. 先补 `my_repositories.user_id` 与 D1 同步，再做按用户画像（工作量较大，建议随 M3-07 推进）；
- **默认处理**：A + C 后续排期；单用户自托管场景下当前口径可用。

## Q14. 每日评估的质量分权重与阈值（REQ-202610-0930 新增）

- **背景**：M4-01 每日评估采用规则口径：`quality_score = 仓库质量 × 0.7 + 理由质量 × 0.3`，
  匹配度硬门槛 `EVAL_MATCH_THRESHOLD=0.35`、质量分门槛 `EVAL_QUALITY_THRESHOLD=0.55`。
  该组默认值基于当前热榜字段完整度与 hash 兜底向量分布，尚未用真实样本校准；
- **选项**：
  - A. 先按默认值上线，M3-08 / M4-09 用抽样评估集校准权重与阈值（**当前默认**）；
  - B. 由维护者直接指定权重 / 阈值；
- **默认处理**：A；全部参数已配置化（`.env` 的 `EVAL_*`），调参无需改代码，
  重跑 `POST /api/tasks/evaluate-recommendations` 即可按新阈值回补。

## Q15. Telegram 通道的会话口径与多用户支持（REQ-202610-0933 新增）

- **背景**：M4-04 按「单 Bot + 单个 `TELEGRAM_CHAT_ID`」实现每日摘要，摘要取最近 24 小时
  `status=pushed` 的推荐（可按 `user_id` 过滤）；但 VPS 本地 `my_repositories` 暂无 `user_id`，
  多用户场景下画像与推送对象都只能先按单用户处理；
- **选项**：
  - A. 单会话（个人自托管）：一个 Bot 发给一个 chat（私聊或群组），群组需把 Bot 拉入群并允许发言（**当前默认**）；
  - B. 多用户：每个用户绑定自己的 chat id，按用户分别生成摘要与幂等键（需先补用户级画像，建议随 M4-06 推进）；
  - C. 多会话广播：同一份摘要发给多个 chat id（配置改为逗号分隔列表）。
- **默认处理**：A；幂等键已按 `telegram:digest:<date>:<user|all>:<chat>` 预留用户维度，
  升级到 B 只需补用户-会话绑定表与调度参数，无需改发送与分片逻辑。

## Q16. Email 通道的 SMTP 服务商与发件人配置（REQ-202610-0934 新增）

- **背景**：M4-05 已实现 SMTP 投递、送达记录与测试接口，但服务商、发件人域名、
  端口 / TLS 组合属于部署环境信息，仓库只提供 `.env.example` 占位符；
- **选项**：
  - A. 使用现有邮箱服务商的 SMTP（如企业邮箱 / 自建 Postfix）：587 + STARTTLS（**推荐**），
    按服务商要求配置 `EMAIL_SMTP_USERNAME` / `EMAIL_SMTP_PASSWORD` 与 SPF / DKIM；
  - B. 使用 465 隐式 SSL：`EMAIL_SSL=true`、`EMAIL_STARTTLS=false`；
  - C. 匿名中继（仅内网 / 本机）：留空用户名密码，并限制监听来源；
- **默认处理**：A；上线前用 `POST /api/notifications/email/test` 验证连通性，
  确认 `GET /api/notifications/email/status` 的 `configured=true` 且 `lastDelivery.status=sent`。
  发件人域名与退订地址需由维护者按服务商政策确认。
## Q17. 推送回执的服务商适配与签名校验（REQ-202610-0937 新增）

- **背景**：M4-08 提供统一的 `POST /api/push/receipts` 回执入口与幂等语义，但不同服务商的
  回调格式、签名算法、重试策略不一致；Bark / Telegram 官方 API 也不提供逐条送达回执；
- **选项**：
  - A. 当前通用入口 + `X-Internal-Token`，由部署方在服务商控制台配置 webhook 或人工补记（**当前默认**）；
  - B. 为 Email 服务商（如 SES / Mailgun）单独实现签名校验与事件映射适配器；
  - C. 仅人工补记，不接服务商回调；
- **默认处理**：A；后续接入具体服务商时在 `vps/app/api/push.py` 前增加适配层，
  不改变 `push_receipts` 的数据结构与状态机。

## Q18. 限流阈值与多实例口径（REQ-202610-0943 新增）

- **背景**：M5-05 默认 edge 读 300 次/分、写 60 次/分、认证 10 次/分（按用户或 IP 哈希），
  VPS 默认 600 次/分、重接口 120 次/分（进程内滑动窗口）。阈值来自经验值，尚未用真实流量校准；
- **选项**：
  - A. 先用默认值上线，观察 `security_events` 中 `rate_limited` 与 429 比例后再调（**当前默认**）；
  - B. 上线前由维护者按预期并发量直接指定；
  - C. 多 VPS worker 场景引入 Redis 全局限流（当前为进程内计数，多进程各自独立）；
- **默认处理**：A；单机单 worker 部署下进程内限流口径可用，扩容到多 worker 前需评估 C。

## Q19. 备份的异地存储与 D1 恢复策略（REQ-202610-0942 新增）

- **背景**：M5-04 已实现本机 SQLite 快照、D1 导出归档与恢复演练，但备份仍与生产库在同一块磁盘，
  且 D1 恢复依赖 `wrangler d1 execute --remote`（大库可能超时）；
- **选项**：
  - A. 先按当前方案上线，异地 / 对象存储、备份加密与 D1 PITR 作为后续增强（**当前默认**，不阻塞 M5）；
  - B. 本迭代内接入 S3 / R2 等对象存储并加密备份（需要额外凭据与预算）；
  - C. 大库改为「新建 D1 导入 + 切换 Worker 绑定」的恢复演练（需要 Cloudflare 账号操作）；
- **默认处理**：A；运维边界已写入 `docs/guides/backup-restore.md` §9，M9-04 / M5-07 继续跟进。

## Q20. Workers Analytics 数据口径（REQ-202610-0941 新增）

- **背景**：M5-03 需要展示 Workers 请求量 / 错误率。Cloudflare GraphQL Analytics API 需要额外的
  Account Analytics Token，且免费额度与采样口径不可控；
- **选项**：
  - A. edge 中间件自聚合到 D1 `worker_metrics`（按日 / 路由 / 方法 / 状态类），admin 直接读 D1（**当前默认**）；
  - B. 接入 Cloudflare GraphQL Analytics API（需新增 `CF_ANALYTICS_TOKEN`，指标更全但多一处外部依赖）；
- **默认处理**：A。已做路由归一化与内部路由排除控制基数；如后续需要 P50/P95 或边缘节点维度，
  再评估 B 并与本表并行展示。

## Q21. 运维值班、RTO / RPO 与变更窗口（REQ-202610-0945 新增）

- **背景**：M5-07 运维手册需要明确故障响应时限、数据恢复目标与发布窗口；当前为单人维护，
  手册只能给出「建议值」，不能替维护者承诺 SLA；
- **选项**：
  - A. 单人维护口径：P0 30 分钟止血、P1 2 小时恢复、RPO ≤ 24 小时（每日备份）、RTO ≤ 2 小时，
    发布窗口默认 22:00–次日 02:00（**当前默认**，与手册 §7.1 / §8.1 一致）；
  - B. 对外承诺 SLA：需要明确值班表、告警渠道与补偿条款，另行评审；
  - C. 其他：由维护者指定时限与窗口。
- **默认处理**：A；若后续有第二维护者或对外服务承诺，按 B 重新评审并更新手册 §2 / §7.1。

## Q22. Python 依赖锁定方式（REQ-202610-0946 新增）

- **背景**：M5-08 审计发现 `vps/requirements*.txt` 仅使用 `>=` 下限，未锁定精确版本；
  同一份代码在不同时间安装可能得到不同依赖树，也不利于漏洞复现与回滚；
- **选项**：
  - A. 生成 `requirements.lock`（`pip freeze` / `uv lock`），部署与 CI 使用锁定文件，`requirements.txt` 保留为直接依赖清单（**推荐**）；
  - B. 直接把 `requirements.txt` 全部改成 `==` 精确版本（简单但升级需手工维护）；
  - C. 维持现状，仅在发布时记录安装快照；
- **默认处理**：A 作为后续独立需求排期；本需求不强行锁定，避免牵动 torch / 模型等重依赖。

## Q23. 用户数据生命周期与导出 / 删除接口（REQ-202610-0946 新增）

- **背景**：隐私边界复核确认 `users` / `recommendations` 等表尚无保留期策略，也没有数据主体导出 / 删除接口；
  审计以 medium 级别记录该缺口，需产品口径确认保留期与删除范围（是否含审计日志、备份）；
- **选项**：
  - A. 由 M9-06「数据治理与隐私策略落地」统一实现导出 / 删除接口与保留期（**推荐**）；
  - B. 本阶段先提供人工删除流程（邮件 / 运维工单），接口延后；
  - C. 其他：由维护者指定保留期与删除范围；
- **默认处理**：A；在 M9-06 落地前，审计报告持续以 `privacy-lifecycle` medium 项提示。

## Q24. 多轮问答的答案生成与会话持久化（REQ-202610-0956 新增）

- **背景**：M6-09 当前采用确定性模板答案 + 客户端携带最近 20 条消息的无状态回放，
  不依赖 LLM / 网络，测试稳定；但答案表达较固定，刷新页面后会话历史丢失；
- **选项**：
  - A. 维持模板答案 + 客户端历史（**当前默认**）：零迁移、零外部依赖，后续可平滑替换；
  - B. M7-01 模型路由就绪后接入 LLM 改写答案，保留 `[n]` 引用与事实校验，失败回退模板；
  - C. 新增 D1 会话表持久化历史与摘要，支持跨设备继续对话，需要保留期与清理策略；
- **默认处理**：A。若需要更自然的表达，先评估 B；跨设备会话再评估 C。

---

> 处理约定：人工确认任一问题后，更新本文件状态并在 `docs/planning/task-planning.md` 记录。
