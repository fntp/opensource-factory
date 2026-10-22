# 开源项目工厂 · 前端控制台（admin）

「开源项目工厂 / OpenFactory」的 Web 控制台：个人开源资产管理与智能推荐系统的管理界面。

基于 [shadcn-admin](https://github.com/satnaing/shadcn-admin)（MIT © Sat Naing）模板定制，UI 风格延续原模板。

## 功能页面

| 路由 | 页面 | 说明 |
| --- | --- | --- |
| `/` | 仪表盘 | 收录统计、Star 趋势、今日热榜 |
| `/repos` | 我的仓库 | 已收录资产列表、搜索、分类筛选 |
| `/categories` | 分类与标签 | 无限级分类 + 标签云 |
| `/trending` | 每日热榜 | GitHub Trending 抓取结果 |
| `/recommend` | 智能推荐 | 语义匹配推荐（含匹配度与理由） |
| `/notifications` | 通知中心 | 站内通知（全部/未读/已读筛选、标记已读、忽略，侧边栏未读徽标） |
| `/monitoring` | 系统监控 | 健康检查、内存 4G / 磁盘 15G 红线、请求量与错误率、告警确认、Workers 每日指标、日志治理 |
| `/settings/*` | 设置 | 账号、外观、推送偏好（时间 / 阈值 / 通道开关） |
| `/search` | 项目搜索 | 语义检索 / README 全文检索切换，展示命中片段（M6-01） |
| `/sign-in` | 登录 | 仅 GitHub 授权登录（+ 演示模式） |

## 技术栈

- **构建**：Vite 8 + TypeScript 5
- **UI**：React 19 · Tailwind CSS 4 · shadcn/ui（Radix UI）
- **路由**：TanStack Router（文件式路由，`src/routes/`）
- **数据**：TanStack Query
- **状态**：zustand（`src/stores/`）
- **测试**：Vitest 浏览器模式（Playwright / Chromium，无头）

## 本地开发

```bash
npm install
npm run dev        # 开发服务器（默认演示模式）
```

### 环境变量（`.env`）

| 变量 | 说明 |
| --- | --- |
| `VITE_API_BASE_URL` | edge API 地址；**留空则自动进入演示模式**（使用内置演示数据） |
| `VITE_DEMO_MODE` | `true` 强制演示模式（登录页显示「演示模式」按钮） |

> 演示模式下登录页会提供「进入演示模式」按钮，数据由各 feature 的 mock 数据兜底，无需后端即可体验完整界面。

## 常用命令

```bash
npm run lint       # ESLint 检查
npm run build      # 类型检查 + 构建（tsc -b && vite build）
npm run test       # Vitest（无头 Chromium，单次运行）
npm run format     # Prettier 格式化
```

## 目录结构

```
src/
├── components/        # 通用组件（layout / ui / ...）
├── features/          # 业务模块（dashboard / repos / trending / recommend / notifications / categories / auth）
├── routes/            # TanStack Router 文件式路由
├── stores/            # zustand 状态（auth-store 等）
└── lib/               # 工具（api.ts 等）
```

## 与后端的约定

- 统一通过 `src/lib/api.ts` 访问 edge API（`credentials: 'include'`，Cookie 会话）；
- 未登录（401）由会话守卫重定向到 `/sign-in`；
- 接口契约见 [docs/architecture/overview.md](../docs/architecture/overview.md) 第 4 节。

## 部署

构建产物为 `dist/`（含 `public/_redirects`，SPA 回退），部署到 Cloudflare Pages；上线时必须配置 `VITE_API_BASE_URL` 且 `VITE_DEMO_MODE=false`。

## 许可

MIT。模板部分版权归 [@satnaing](https://github.com/satnaing) 所有，详见 [LICENSE](./LICENSE)。
