# 参考项目集成说明 · Reference Projects

> 文档编号：IN-01 ｜ 维护人：fntp ｜ 对应立项要求 #5（功能集成）与 #6（参考项目）

立项要求「结合参考项目把已有功能直接融进来，不用单独去写」。本文档记录三个参考项目的融合方式、现状与注意事项。

## 1. shadcn-admin（admin 模板基线）

- **来源**：https://github.com/satnaing/shadcn-admin （v2.2.1，MIT © Sat Naing）；
- **融合方式**：`admin/` 目录基于其完整模板定制：
  - **保留**：布局体系（Sidebar / Header / Main / ConfigDrawer）、shadcn/ui 组件库、主题系统（light/dark/system）、TanStack Router/Query 架构、工具与测试基建；
  - **删除**：Clerk 集成、注册 / 找回密码 / OTP 页面、演示业务模块（tasks / apps / chats / users / help-center）、Netlify 配置；
  - **重写**：登录页（仅 GitHub + 演示模式）、会话守卫、仪表盘、侧边栏数据（四大导航组）、品牌（Logo / 标题 / 中文文案）；
  - **新增**：`features/{repos,trending,recommend,categories}` 四个业务模块 + 对应路由；
- **许可**：保留 `admin/LICENSE` 原始版权声明（MIT 允许商用与修改，须保留声明）。

## 2. bookmark-recommender（后端能力来源）

- **来源**：内部参考项目（FastAPI + SQLAlchemy + ChromaDB + sentence-transformers）；
- **融合方式**：能力移植（适配本系统架构，非直接依赖）：
  | 参考能力 | 移植落位 | 适配说明 |
  | --- | --- | --- |
  | `github_service.py`（Starred 拉取 / 仓库详情 / README） | `vps/app/services/github_service.py` | 改为 httpx 异步、标准化输出字段 |
  | `scraper.py`（httpx + bs4 基建） | `vps/app/services/trending_crawler.py` | 目标改为 GitHub Trending 榜单解析 |
  | `embedding.py`（编码 / 语义检索） | `vps/app/services/embedding.py` | 升级为 BGE-M3 优先 + 确定性哈希降级 |
  | `ai_service.py` / 摘要链路 | `vps/app/services/summarizer.py` | Ollama 优先，DeepSeek 降级，中文摘要 |
  | 推荐编排（`_run_recommendation`） | `vps/app/services/recommender.py` | 余弦相似度 + 理由生成 |
  | API 设计（github / recommend 路由） | `edge/src/routes/*` + `vps/app/api/*` | 拆分：读走 edge，算走 vps |
- **数据模型差异**：参考项目用 `br_*` 前缀表；本系统按需求规范改为 `my_repositories` / `trending_repositories` / `categories`（见 data-model）。

## 3. github_trending（⚠️ 无法访问）

- **状态**：需求中提供的参考项目 `github_trending` 仓库 **返回 404**，无法获取代码（已多路径核实：直接访问、搜索、镜像、同组织仓库均不可得）；
- **替代方案（当前）**：自研最小化 Trending 爬虫 `vps/app/services/trending_crawler.py`：
  - 解析 github.com/trending 页面（`article.Box-row`），提取仓库名 / 描述 / 语言 / 今日与总 Star；
  - 纯函数解析器便于测试（fixture 驱动，不依赖网络）；
  - 预留 Gitee 探索页抓取入口（M2 实现）；
- **待办**：请维护者提供可用地址 / 权限（见 `docs/requirements/open-questions.md` Q1），获得后对齐替换。

## 4. 集成原则（复用而非堆砌）

1. **能力移植**：只搬「能力与经验」，接口与数据模型按本系统规范重塑；
2. **降级优先**：所有外部依赖（LLM / 模型 / 站点）必须有兜底路径；
3. **归属清晰**：第三方代码遵循其许可证（MIT 等），保留版权声明；内部参考项目代码以本仓库规范重构后合入。
