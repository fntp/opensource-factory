# 实施计划 · REQ-202610-0973 快捷入口（Raycast / 快捷指令类）评估

> 需求：REQ-202610-0973（backlog M8-04）｜ 分支：`feat/req-202610-0973-quick-entry-eval`
> 依赖：M8-05 开放 API（个人令牌，平台仍 pending）
> 目标：对「Raycast / Apple 快捷指令 / Alfred / uTools / 浏览器地址栏 / VS Code」等快捷入口做**可复跑的量化评估**，给出首发平台、API 前置条件、落地路线与安全边界，而不是只写主观对比。

## 1. 现状与约束

- 当前 edge 只提供浏览器会话（`of_session` Cookie）鉴权，没有面向第三方客户端的个人令牌；
  Raycast / 快捷指令无法复用 Cookie 会话，必须先完成 M8-05 的开放 API；
- 浏览器扩展（M8-02）已经覆盖「一键收藏当前页面」，快捷入口的差异化价值是
  **全局热键 / 系统分享面板 / 语音唤起**，不是重复做收藏按钮；
- 本机是 Linux VPS，Raycast / Alfred / 快捷指令均无法在本机做真机验收；
  评估工具必须离线可跑，真机验收作为人工待办明确列出；
- 个人令牌属于高敏凭据：客户端（尤其是 iCloud 同步的快捷指令）不能持有全权限长期令牌，
  必须支持只读 / 读写分 scope、即时撤销、最近使用审计与限流。

## 2. 评估问题拆解

| # | 问题 | 产出 |
| --- | --- | --- |
| 1 | 哪些平台值得做 | 候选平台目录与加权评分 |
| 2 | 每个平台的真实成本 | 开发工作量、安装门槛、审核 / 维护成本 |
| 3 | 认证怎么做才安全 | 个人令牌 + scope + 撤销 + 审计的 API 前置清单 |
| 4 | 先做哪个、后做哪个 | 排名、推荐路线与触发条件 |
| 5 | 做完怎么验收 | 真机清单、接口契约测试、成功率 / 延迟指标 |
| 6 | 哪些点需要人拍板 | open-questions 记录（平台优先级、快捷指令令牌存储） |

## 3. 实现方案

### 3.1 评估工具（新增）

`vps/app/services/quick_entry_eval.py`（仅标准库，不依赖网络 / 数据库 / 第三方包）：

- `CRITERIA`：8 项评估维度与权重（覆盖 20% / 认证 20% / 体验 15% / 开发成本 15% /
  维护 10% / 安装 10% / 离线 5% / 生态 5%）；
- `PLATFORMS`：6 个候选平台（Raycast、Apple 快捷指令、浏览器地址栏、VS Code、
  Alfred、uTools）的分项 1–5 分、亮点、局限与结论；
- `score_platform()` / `rank_platforms()`：加权求和、稳定排序、等级判定；
- `API_REQUIREMENTS`：M8-05 必须提供的 16 项能力（令牌签发 / 列表 / 撤销、Bearer、
  读写 scope、限流、幂等、搜索、收藏 / 取消收藏、`/me`、OpenAPI、CORS、深链、审计）；
- `assess_api_readiness(ready_keys)` / `platform_readiness()`：按平台给出「可开工 / 被阻塞」
  与缺失能力清单；
- `build_evaluation()`：汇总排名、API 就绪度、分阶段路线、风险与指标；
- `render_markdown()` / `render_contract()`：生成归档报告与机器可读契约；
- CLI：
  ```bash
  cd vps
  .venv/bin/python -m app.quick_entry_eval report
  .venv/bin/python -m app.quick_entry_eval report --json
  .venv/bin/python -m app.quick_entry_eval report --ready all
  .venv/bin/python -m app.quick_entry_eval contract --out docs/assets/quick-entry-api-contract.json
  ```

### 3.2 评估报告（新增）

`docs/architecture/quick-entry-evaluation.md`：

- 结论摘要与推荐顺序；
- 评估方法、权重与评分表；
- 每个平台的亮点 / 局限 / 适用人群；
- M8-05 API 就绪度清单与阻塞项；
- 分阶段落地路线（M8-05 → Raycast MVP → 快捷指令 → 浏览器地址栏复用 M8-02）；
- 安全与隐私边界、风险登记、验收指标、复跑方式。

### 3.3 机器可读契约（新增）

`docs/assets/quick-entry-api-contract.json`：

- `openfactory.quick-entry.v1` schema；
- 平台能力矩阵与 API 要求；
- 建议的 `/api/v1/*` 端点、scope、幂等与错误约定，作为 M8-05 的实现输入。

### 3.4 文档同步

- `docs/README.md` 增加评估报告、计划与契约入口；
- `docs/planning/roadmap.md` 勾选 M8-04 评估完成；
- `docs/planning/task-planning.md` 新增 IT-0064 与交付记录；
- `docs/requirements/backlog.md` 标注 M8-04 完成；
- `docs/requirements/open-questions.md` 新增 Q35（首发平台与快捷指令令牌存储）。

## 4. 文件清单

- 新增 `vps/app/services/quick_entry_eval.py`（评估逻辑）
- 新增 `vps/app/quick_entry_eval.py`（`python -m app.quick_entry_eval` CLI 入口转发）
- 新增 `vps/tests/test_quick_entry_eval.py`
- 新增 `docs/planning/plan-req-202610-0973-quick-entry-eval.md`（本文件）
- 新增 `docs/architecture/quick-entry-evaluation.md`
- 新增 `docs/assets/quick-entry-api-contract.json`
- 修改 `docs/README.md`、`docs/planning/roadmap.md`、`docs/planning/task-planning.md`、
  `docs/requirements/backlog.md`、`docs/requirements/open-questions.md`、
  `docs/architecture/overview.md`

## 5. 验证计划

```bash
cd vps && .venv/bin/pytest -q tests/test_quick_entry_eval.py
cd vps && .venv/bin/pytest -q
cd vps && .venv/bin/python -m app.quick_entry_eval report
cd vps && .venv/bin/python -m app.quick_entry_eval report --json
cd vps && .venv/bin/python -m app.quick_entry_eval contract --out docs/assets/quick-entry-api-contract.json
git diff --check
```

## 6. 边界

- 本需求**不实现 M8-05 开放 API、不新增 edge 路由 / D1 表、不改 admin**；
  产出是评估工具、报告、API 契约与实施建议；
- 评分是 2026-10 的产品判断，权重与分数可在 `quick_entry_eval.py` 调整并复跑；
- 真机验收（Raycast 商店安装、iPhone 快捷指令、Alfred / uTools）本机无法完成，
  列入「仍需人工处理」并在报告中给出验收步骤；
- 不采集任何真实令牌；示例中的令牌一律为占位符。
