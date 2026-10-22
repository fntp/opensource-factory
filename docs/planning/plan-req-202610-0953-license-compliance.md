# 实施计划 · REQ-202610-0953 License 识别与合规提示

> 需求：REQ-202610-0953（backlog M6-06）｜ 分支：`feat/req-202610-0953-license-compliance`
> 依赖：M2-03 README 清洗强化（已具备 `readme.py` 清洗与元数据提取基础）
> 目标：识别仓库 License，按「宽松 / 弱著佐权 / 强著佐权 / 网络著佐权 / 未知」给出合规提示，
> 并在热榜、我的仓库与独立合规视图中展示，避免误用无许可证或高风险许可证的项目。

## 1. 现状与缺口

- `vps/app/services/readme.py` 已能清洗 README 并提取技术栈，但没有 License 识别；
- `github_service.normalize_repo()` 丢弃了 GitHub API 返回的 `license` 对象，`MyRepository` /
  `TrendingRepository` 也没有 License 字段；
- GitHub Trending HTML 不包含 License，热榜项目需要异步补全；
- admin 热榜列表 / 详情、我的仓库均无 License 展示，也没有合规提示；
- D1 `my_repositories` / `trending_repositories` 无 License 列，edge DTO 无对应字段。

## 2. 方案总览

```text
VPS
  app/services/license.py         License 目录 / 归一化 / README 识别 / 合规分级
  app/services/github_service.py  normalize_repo 保留 license 对象
  app/tasks/jobs.py               sync 落库 + enrich_licenses 异步补全 + 每日 beat
  app/api/licenses.py             catalog / summary / 单仓库合规查询
  app/api/tasks.py                POST /api/tasks/enrich-licenses

D1（edge/migrations/0010_license_compliance.sql）
  my_repositories / trending_repositories 增加
  license_spdx / license_name / license_source / license_checked_at

edge
  src/license/compliance.ts       合规目录与分类（与 VPS 口径一致）
  src/routes/licenses.ts          GET /api/licenses/catalog、/api/licenses/summary
  src/routes/internal-licenses.ts POST /api/internal/licenses（VPS 回写）
  repos / trending 路由           DTO 增加 license，列表按许可证筛选

admin
  热榜列表 / 详情                  License 徽章 + 合规提示卡片
  我的仓库                         License 列
  /licenses                       合规总览：风险分布、许可证分布、义务说明
```

## 3. 合规分级口径

| 分类 | 典型 SPDX | 风险 | 核心提示 |
| --- | --- | --- | --- |
| `permissive` 宽松 | MIT / Apache-2.0 / BSD-2/3-Clause / ISC | 低 | 保留版权与许可证文本；Apache-2.0 需保留 NOTICE |
| `weak-copyleft` 弱著佐权 | MPL-2.0 / LGPL-2.1 / LGPL-3.0 / EPL-2.0 | 中 | 修改的库文件需开源；动态链接通常可闭源 |
| `strong-copyleft` 强著佐权 | GPL-2.0 / GPL-3.0 | 高 | 分发衍生作品需以同许可证开源 |
| `network-copyleft` 网络著佐权 | AGPL-3.0 | 高 | 通过网络提供服务也可能触发源码开放 |
| `public-domain` 公共领域 | Unlicense / CC0-1.0 | 低 | 无强制义务，建议保留出处 |
| `unknown` 未知 | 无 / NOASSERTION / 未收录 | 未知 | 默认保留所有权利，商用 / 分发前需联系作者授权 |

识别优先级：GitHub API `license.spdx_id` → README 许可证段落 / 徽章启发式 → `unknown`。
`license_source` 记录来源（`github` / `readme` / `none`），便于排查与重跑。

## 4. 数据模型

`my_repositories` 与 `trending_repositories` 各追加 4 列（D1 迁移 + VPS SQLite 幂等补列）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| license_spdx | TEXT | SPDX 标识（如 MIT / Apache-2.0 / AGPL-3.0） |
| license_name | TEXT | 展示名称（如 MIT License） |
| license_source | TEXT | github / readme / none |
| license_checked_at | DATETIME | 最近一次识别时间 |

## 5. 交付物

| 文件 | 说明 |
| --- | --- |
| `vps/app/services/license.py` | License 目录、归一化、README 识别、合规提示与分布统计 |
| `vps/app/services/github_service.py` | `normalize_repo` 增加 license 字段 |
| `vps/app/models.py` / `vps/app/db.py` | 模型列与 SQLite 幂等补列 |
| `vps/app/tasks/jobs.py` / `celery_app.py` | 同步落库、`enrich_licenses` 任务、每日 beat |
| `vps/app/api/licenses.py` / `tasks.py` / `main.py` | License 查询与补全入队接口 |
| `vps/tests/test_license.py` | 识别、分级、API 与任务测试 |
| `edge/migrations/0010_license_compliance.sql` | D1 License 列与索引 |
| `edge/src/license/compliance.ts` | 合规目录 / 分级纯函数 |
| `edge/src/routes/licenses.ts` / `internal-licenses.ts` | 合规目录、分布统计、内部回写 |
| `edge/src/routes/repos.ts` / `trending.ts` | DTO 增加 license 与筛选 |
| `edge/scripts/license-compliance.test.mjs` | edge 纯函数测试 |
| `admin/src/features/licenses/*` / `routes/_authenticated/licenses/index.tsx` | 合规总览页 |
| `admin/src/features/trending/*` / `repos/*` | License 徽章与详情提示 |
| `docs/*` | 架构、数据模型、backlog、roadmap、task-planning、README、open-questions |

## 6. 测试与验收

| 层 | 用例 |
| --- | --- |
| vps | `tests/test_license.py`：GitHub 对象归一化、README 识别、分级、未知回退、catalog / summary / 单仓库 API、enrich 任务（fake fetcher） |
| edge | `node --test scripts/license-compliance.test.mjs`：SPDX 归一化、分类、未知回退、DTO 映射、统计聚合 |
| admin | `license.test.ts`：风险标签、分布聚合、筛选；`detail.test.ts` 增加 License 元信息断言 |
| 全量 | admin lint / build / test；edge typecheck / test；vps pytest |

验收标准：

1. 已同步仓库与热榜项目都能返回 `license` 结构化信息（未知时给出明确提示）；
2. 合规提示覆盖宽松 / 弱著佐权 / 强著佐权 / 网络著佐权 / 未知五类，并给出义务与风险；
3. 支持异步补全存量数据，重复执行幂等；未配置 GitHub Token 时安全跳过；
4. D1 / SQLite 迁移幂等，三端检查全绿；
5. 文档索引、backlog、roadmap、task-planning 同步更新。

## 7. 风险与后续

- **法律口径**：合规提示是工程辅助信息，不构成法律意见；在页面与文档中明确免责声明；
- **GitHub 限流**：未配置 Token 时匿名 60 次/小时，补全任务按批限量并允许失败重试；
- **Gitee**：当前只覆盖 GitHub API 与 README 启发式，Gitee 许可证字段后续按开放平台补；
- **识别误差**：README 启发式可能误判，保留 `license_source` 与人工修正入口（后续需求）；
- **并行分支**：M6-01/02/03/04/05 在独立分支开发，合并时注意 D1 迁移编号与文档冲突。

## 8. 实施结果

- **识别链路**：VPS `license_enrichment.enrich_licenses` 按 `scope=my|trending|all` 扫描未识别仓库，
  GitHub API `license.spdx_id` 优先，缺失时回退 README（SPDX 标识 / shields 徽章 / 许可证名称），
  写回 `license_spdx` / `license_name` / `license_source` / `license_checked_at`；
  每日 06:47 Celery beat 自动补全，另提供 `POST /api/tasks/enrich-licenses`（支持 `force`）。
- **分级与提示**：VPS 与 edge 各维护一份同构目录（16 种常见 SPDX），覆盖宽松 / 弱著佐权 / 强著佐权 /
  网络著佐权 / 公共领域 / 未知六类，输出 `riskLevel`、`obligations`、`warnings`；未知许可证给出
  「无许可证不等于可以自由使用」提示。分类在读取时派生，不落库。
- **D1**：`0010_license_compliance.sql` 为 `my_repositories` / `trending_repositories` 增加四列与
  `license_spdx` 索引；热榜快照查询 LEFT JOIN 最新状态表补齐 License；收藏热榜时复制 License 字段。
- **接口**：edge `GET /api/licenses/catalog`、`GET /api/licenses/summary`，内部回写
  `POST /api/internal/licenses`；VPS `GET /api/licenses/catalog|summary`、`GET /api/repos/{id}/license`。
- **admin**：新增 `/licenses` 合规总览（覆盖率、风险分布、目录与义务），仓库列表 / 热榜列表增加
  License 徽章，热榜详情页新增合规提示卡片与免责声明。
- **验证**：VPS `pytest` 249 用例全绿；edge `tsc --noEmit` + `node --test` 36 用例全绿；
  admin `lint` / `build` / `test` 全绿（99 用例）。
- **遗留**：Gitee 许可证字段未接入（见 open-questions Q14）；README 启发式可能误判，后续可加人工修正入口。
