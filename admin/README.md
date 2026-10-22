# 开源项目工厂 · 前端控制台（admin）

「开源项目工厂 / OpenFactory」的 Web 控制台：个人开源资产管理与智能推荐系统的管理界面。

基于 [shadcn-admin](https://github.com/satnaing/shadcn-admin)（MIT © Sat Naing）模板定制，UI 风格延续原模板。

## 功能页面

| 路由                    | 页面       | 说明                                                                                    |
| ----------------------- | ---------- | --------------------------------------------------------------------------------------- |
| `/`                     | 仪表盘     | 收录统计、Star 趋势、今日热榜                                                           |
| `/repos`                | 我的仓库   | 已收录资产列表、搜索、分类筛选；健康度汇总 / 筛选 / 徽章与手动刷新（M6-05）             |
| `/categories`           | 分类与标签 | 无限级分类 + 标签云                                                                     |
| `/trending`             | 每日热榜   | GitHub Trending 抓取结果；详情页含「看了又看」相似项目推荐（M6-02）                     |
| `/export`               | 知识库导出 | Markdown / JSON / Obsidian 三种格式，支持摘要开关与分类分组（M6-08）                    |
| `/recommend`            | 智能推荐   | 语义匹配推荐（含匹配度与理由）                                                          |
| `/notifications`        | 通知中心   | 站内通知（全部/未读/已读筛选、标记已读、忽略，侧边栏未读徽标）                          |
| `/monitoring`           | 系统监控   | 健康检查、内存 4G / 磁盘 15G 红线、请求量与错误率、告警确认、Workers 每日指标、日志治理 |
| `/tech-stack`           | 技术栈图谱 | 语言 / 框架聚合 KPI、语言 × 框架径向关系图、语言分布、框架排行、组合洞察                |
| `/settings/*`           | 设置       | 账号、外观、推送偏好（时间 / 阈值 / 通道开关）                                          |
| `/search`               | 项目搜索   | 语义检索 / README 全文检索切换，展示命中片段（M6-01）                                   |
| `/duplicates`           | 重复检测   | 重复 / 相似项目扫描、保留项与字段合并建议、按用户忽略（M6-03）                          |
| `/dependencies`         | 依赖分析   | 技术栈分布、热门依赖、生态构成与仓库覆盖（M6-07）                                       |
| `/tag-suggestions`      | 打标建议   | 基于摘要的标签建议，按仓库分组，支持单条 / 整仓采纳与忽略（M7-01）                      |
| `/category-suggestions` | 分类建议   | 按业务线自动生成可解释的分类建议，支持采纳写回分类 / 忽略（M7-02）                      |
| `/sign-in`              | 登录       | 仅 GitHub 授权登录（+ 演示模式）                                                        |

## 技术栈

- **构建**：Vite 8 + TypeScript 5
- **UI**：React 19 · Tailwind CSS 4 · shadcn/ui（Radix UI）
- **路由**：TanStack Router（文件式路由，`src/routes/`）
- **数据**：TanStack Query
- **状态**：zustand（`src/stores/`）
- **测试**：Vitest 浏览器模式（Playwright / Chromium，无头）
- **PWA**：手写 Web App Manifest + Service Worker（无额外构建插件）

## PWA 与移动端

- **安装**：`public/manifest.webmanifest` 提供独立窗口（`standalone`）、主题色与 192 / 512 / maskable 图标；`index.html` 含 iOS `apple-touch-icon` 与 `apple-mobile-web-app-*` 元信息。
- **离线**：`public/sw.js` 预缓存 App Shell（`/`、离线页、manifest、图标），导航请求网络优先并回退 `/offline.html`；同源静态资源缓存优先；`/api/*`、非 GET 与跨域请求不拦截。
- **更新**：Service Worker 采用 `skipWaiting` + `clients.claim`，检测到新版本时页面通过 sonner 提示「立即刷新」。修改静态资源后请同步提升 `sw.js` 中的 `CACHE_VERSION`。
- **安装引导**：`src/components/pwa/pwa-provider.tsx` 监听 `beforeinstallprompt` / `appinstalled`，桌面与 Android 提供安装按钮，iOS Safari 展示「分享 → 添加到主屏幕」说明；关闭后 7 天内不再提示（`src/lib/pwa.ts`）。
- **移动端**：`src/components/layout/mobile-tab-bar.tsx` 在 `< md` 显示底部主导航（仪表盘 / 仓库 / 热榜 / 推荐），配合 `env(safe-area-inset-*)` 适配刘海与底部安全区；仓库页在窄屏切换为卡片列表，热榜隐藏次要列，搜索与配置入口按断点收窄。
- **注册时机**：`src/lib/service-worker.ts` 仅在 `import.meta.env.PROD` 下注册，开发模式不启用缓存，避免调试时读到旧资源。

## 本地开发

```bash
npm install
npm run dev        # 开发服务器（默认演示模式）
```

### 环境变量（`.env`）

| 变量                | 说明                                                          |
| ------------------- | ------------------------------------------------------------- |
| `VITE_API_BASE_URL` | edge API 地址；**留空则自动进入演示模式**（使用内置演示数据） |
| `VITE_DEMO_MODE`    | `true` 强制演示模式（登录页显示「演示模式」按钮）             |

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
├── components/        # 通用组件（layout / ui / pwa / ...）
├── features/          # 业务模块（dashboard / repos / trending / recommend / notifications / categories / auth）
├── routes/            # TanStack Router 文件式路由
├── stores/            # zustand 状态（auth-store 等）
└── lib/               # 工具（api.ts / pwa.ts / service-worker.ts 等）
public/
├── manifest.webmanifest  # PWA 清单
├── sw.js                 # Service Worker（缓存策略与版本）
├── offline.html          # 离线兜底页
└── icons/                # PWA / apple-touch 图标
```

## 与后端的约定

- 统一通过 `src/lib/api.ts` 访问 edge API（`credentials: 'include'`，Cookie 会话）；
- 未登录（401）由会话守卫重定向到 `/sign-in`；
- 接口契约见 [docs/architecture/overview.md](../docs/architecture/overview.md) 第 4 节。

## 部署

构建产物为 `dist/`（含 `public/_redirects`，SPA 回退），部署到 Cloudflare Pages；上线时必须配置 `VITE_API_BASE_URL` 且 `VITE_DEMO_MODE=false`。

## 许可

MIT。模板部分版权归 [@satnaing](https://github.com/satnaing) 所有，详见 [LICENSE](./LICENSE)。
