# 实施计划 · REQ-202610-0954 依赖分析（项目依赖 ↔ 个人技术栈关联）

> 需求：REQ-202610-0954（backlog M6-07）｜ 分支：`feat/req-202610-0954-dependency-analysis`
> 依赖：M6-04 技术栈图谱（REQ-202610-0951）
> 日期：2026-10-22｜ 状态：已完成

## 1. 目标

把「项目依赖」从散落在各仓库清单文件里的原始信息，变成可查询的个人技术资产：

1. **清单解析**：支持 npm / PyPI / Go / Cargo / Maven / RubyGems / Composer 常见依赖清单；
2. **依赖入库**：扫描个人收藏仓库的清单，按仓库落库 `repo_dependencies`，记录版本、运行时 / 开发依赖与来源文件；
3. **技术栈关联**：按语言统计个人技术栈，计算每个依赖的仓库覆盖率、语言分布与「依赖 × 语言」关联强度；
4. **可视化**：admin 新增「依赖分析」页，展示技术栈分布、热门依赖、生态构成与仓库覆盖明细；
5. **降级可用**：VPS 不可达时 edge 用 D1 语言数据给出本地概览，admin 用演示数据兜底。

## 2. 现状与缺口

- 现有模型只保存仓库的 `language` 与 `readme_summary`，没有依赖清单与依赖表；
- M6-04 技术栈图谱只做语言 / 框架聚合，回答不了「我的项目实际依赖了哪些库、这些库和我的语言栈怎么对应」；
- GitHub 同步没有抓取清单文件，需要新增按需扫描（避免把同步任务做得过重）；
- 依赖数据是「仓库 × 依赖」的多对多关系，需要独立表与扫描状态表支撑覆盖率统计。

## 3. 方案

### 3.1 数据模型（VPS SQLite）

```
repo_dependencies
  id            TEXT PK      -- sha1(repo_id|ecosystem|name|kind) 前 16 位
  repo_id       TEXT INDEX   -- owner/repo
  ecosystem     TEXT         -- npm | pypi | go | cargo | maven | rubygems | composer
  name          TEXT         -- 规范化后的依赖名
  version       TEXT NULL    -- 原始版本约束（不做语义化解析）
  kind          TEXT         -- runtime | dev
  manifest      TEXT         -- package.json / requirements.txt ...
  updated_at    DATETIME

repo_dependency_scans
  repo_id         TEXT PK
  status          TEXT       -- ok | no_manifest | failed
  manifests       TEXT       -- 命中的清单文件，逗号分隔
  dependency_count INTEGER
  error           TEXT NULL
  scanned_at      DATETIME
```

依赖表只存在 VPS 本地，不复制到 D1；edge 按当前用户的仓库 id 向 VPS 查询，
避免把多用户依赖明细落到边缘库。

### 3.2 清单解析

| 生态 | 清单文件 | 解析规则 |
| --- | --- | --- |
| npm | `package.json` | `dependencies` / `peerDependencies` 为 runtime，`devDependencies` 为 dev |
| PyPI | `requirements.txt` | 跳过注释 / 选项行，解析 `name[extra]` 与版本约束 |
| PyPI | `pyproject.toml` | `[project].dependencies`、`[project.optional-dependencies]`、Poetry 依赖表 |
| Go | `go.mod` | `require` 单行与块，模块路径为依赖名 |
| Cargo | `Cargo.toml` | `[dependencies]` / `[dev-dependencies]` / `[build-dependencies]` |
| Maven | `pom.xml` | `<dependency>` 的 `groupId:artifactId`，`scope=test` 记为 dev |
| RubyGems | `Gemfile` | `gem "name", "version"`，`group :development/:test` 记为 dev |
| Composer | `composer.json` | `require` 为 runtime，`require-dev` 为 dev |

- 解析函数均为纯函数，输入文本输出 `Dependency` 列表，便于单测与离线复用；
- 名称规范化：PyPI 小写并把 `_` / `.` 归一为 `-`，npm 保留 scope（`@scope/name`），其余 trim；
- 版本只保留原始约束字符串，不做范围求交，避免引入 semver 解析依赖。

### 3.3 扫描与聚合

- `scan_repositories()`：按仓库拉取候选清单（GitHub Contents API / raw），解析后覆盖式写入；
  单仓库失败只记录 `failed`，不阻断整批；默认只扫最近未扫描的仓库，`force=True` 强制重扫；
- `aggregate_dependencies()`：读取仓库、扫描状态与依赖，输出：
  - `summary`：仓库数 / 已分析 / 无清单 / 失败 / 依赖行数 / 唯一依赖数；
  - `techStack`：语言分布（数量 + 占比）；
  - `ecosystems`：各生态覆盖仓库数与依赖行数；
  - `dependencies`：按仓库覆盖率排序的依赖，含版本样例、语言分布、代表项目；
  - `links`：依赖 × 语言关联强度（同依赖下该语言仓库占比）；
  - `repos`：逐仓库覆盖明细与 Top 依赖。
- 聚合只读本地表，不触发网络；扫描通过独立接口 / Celery 任务触发。

### 3.4 接口

| 层 | 接口 | 说明 |
| --- | --- | --- |
| VPS | `GET /api/analysis/dependencies?repoIds=&top=` | 聚合查询（内部令牌） |
| VPS | `POST /api/analysis/dependencies/refresh` | 按仓库 id 扫描清单并入库（内部令牌） |
| VPS | Celery `analyze_dependencies` | 异步扫描入口，供运维 / 定时补扫 |
| edge | `GET /api/analysis/dependencies?top=` | 当前用户仓库 id → VPS 聚合；失败回退 D1 语言概览 |
| edge | `POST /api/analysis/dependencies/refresh` | 当前用户仓库扫描（限制数量） |

### 3.5 admin 页面

- 路由 `/dependencies`，侧边栏「开源资产 → 依赖分析」；
- 概览卡：已分析项目、唯一依赖、生态数、技术栈语言数；
- 技术栈分布：语言条形占比；
- 热门依赖：生态 / 类型徽标、覆盖仓库数、版本样例、语言分布、代表项目；
- 仓库覆盖：扫描状态、清单数、依赖数、Top 依赖；
- 「刷新分析」按钮触发扫描并重新加载；接口不可用时使用演示数据。

## 4. 文件清单

| 文件 | 说明 |
| --- | --- |
| `vps/app/models.py` | 新增 `RepoDependency` / `RepoDependencyScan` |
| `vps/app/services/dependency_analysis.py` | 清单解析、扫描、聚合 |
| `vps/app/api/analysis.py` | 聚合 / 刷新接口 |
| `vps/app/schemas.py` | 依赖分析出入参 |
| `vps/app/tasks/jobs.py` | `analyze_dependencies` Celery 任务 |
| `vps/tests/test_dependency_analysis.py` | 解析 / 扫描 / 聚合 / API 测试 |
| `edge/src/routes/analysis.ts` | 用户级聚合与刷新代理 |
| `edge/src/dependencies/helpers.ts` | 参数归一化与本地降级 |
| `edge/scripts/dependency-helpers.test.mjs` | edge 纯函数测试 |
| `admin/src/features/dependencies/*` | API / 工具 / 页面 / 测试 |
| `admin/src/routes/_authenticated/dependencies/index.tsx` | 页面路由 |
| 文档 | 架构总览、数据模型、backlog、roadmap、task-planning、三端 README |

## 5. 测试与验收

| 层 | 用例 |
| --- | --- |
| vps | 8 类清单解析、名称规范化、扫描覆盖写入 / 失败降级、聚合统计与仓库过滤、API 契约 |
| edge | top 参数归一化、repoIds 解析、本地语言降级、空数据 |
| admin | 占比 / 标签 / 时间格式化纯函数，页面渲染由 build + lint 保证 |

验收标准：

1. 解析器覆盖 8 类清单，异常文本返回空列表而不抛错；
2. 扫描后 `repo_dependencies` 与 `repo_dependency_scans` 正确落库，重复扫描不产生重复行；
3. 聚合结果包含技术栈、生态、依赖覆盖率与依赖 × 语言关联；
4. edge 只返回当前用户仓库的数据，VPS 不可达时仍可展示语言概览；
5. admin 页面可加载、可刷新、演示模式可用；
6. vps pytest、edge typecheck / test、admin lint / build / test 全绿。

## 6. 风险与后续

- **清单覆盖有限**：仅识别常见清单，Gradle / Bazel / 私有 registry 等暂不支持，记录 open-question；
- **GitHub 限流**：按需扫描并限制单次仓库数，失败仓库保留旧数据并标记 `failed`；
- **版本约束不解析**：只展示原始字符串，后续可接入 semver / PEP 440 做冲突检测；
- **依赖安全**：本期不做漏洞库比对，后续可与安全审计（M5-08）联动；
- **M6-04 依赖**：技术栈图谱分支尚未合并时，本期以仓库 `language` + 依赖生态自行聚合，合并后可复用其图谱视图。
