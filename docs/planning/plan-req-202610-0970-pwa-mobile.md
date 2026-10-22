# 实施计划 · REQ-202610-0970 PWA 与移动端适配

> 需求：REQ-202610-0970（backlog M8-01）｜ 分支：`feat/req-202610-0970-pwa-mobile`
> 依赖：M5-01 正式部署（本需求不依赖线上域名，先落地可安装 / 可离线的前端壳）
> 基线：`feat/req-202610-0969-m7-acceptance` @ `2cd87b3`
> 目标：让 admin 控制台可安装为 PWA，并在手机窄屏下具备可用的导航、列表与安装引导。

## 1. 现状与缺口

- `admin/index.html` 只有基础 viewport 与 favicon，没有 manifest、apple-touch-icon、
  `viewport-fit=cover` 等移动端 / 安装相关元信息；
- `admin/public/` 没有 Service Worker、离线兜底页与 PWA 图标，浏览器不会给出安装入口；
- 侧边栏在移动端已通过 Sheet 抽屉降级，但缺少底部主导航，长页面只能靠抽屉来回切换；
- 仓库页 7 列表格在手机上只能横向滚动，首屏信息密度低；部分页面标题与操作按钮同行，
  窄屏会挤压；
- 安装 / 离线状态没有任何界面反馈，用户不知道应用可以安装、当前离线。

## 2. 方案总览

```
admin/
├─ public/
│  ├─ manifest.webmanifest      # 名称 / 图标 / 主题色 / 快捷方式 / standalone
│  ├─ sw.js                     # App Shell 预缓存 + 导航网络优先 + 静态资源缓存优先
│  ├─ offline.html              # 离线兜底页（纯内联样式，无外部依赖）
│  └─ icons/                    # 192 / 512 / maskable / apple-touch-icon
├─ src/lib/pwa.ts               # 纯函数：standalone / iOS / 安装提示冷却
├─ src/lib/service-worker.ts    # 仅生产环境注册 SW，监听更新
├─ src/components/pwa/pwa-provider.tsx  # 离线横幅 + 安装引导 + 更新提示
├─ src/components/layout/mobile-tab-bar.tsx # 移动端底部主导航
└─ index.html / main.tsx / layout / styles / 关键页面
```

设计原则：

1. **不引入新依赖**：手写 manifest / SW，避免为 PWA 增加构建插件与体积；
2. **安装与离线分离**：本需求只做 PWA 壳与基础 App Shell 缓存；离线数据读写属于 M8-07；
3. **渐进增强**：不支持 SW 的浏览器、开发模式、注册失败都不影响主流程；
4. **移动优先但不破坏桌面**：底部导航仅 `< md` 显示，桌面布局与交互保持不变；
5. **安全**：SW 只缓存同源 GET 静态资源，跳过 `/api/*`，不缓存任何鉴权响应体。

## 3. 关键实现

### 3.1 Manifest

- `name` / `short_name`：开源项目工厂 / 开源项目工厂
- `start_url` / `scope` / `id`：`/`
- `display: standalone`、`orientation: any`、`lang: zh-CN`
- 图标：192 / 512 普通图标 + 192 / 512 maskable 图标 + 180 apple-touch-icon
- `shortcuts`：我的仓库 `/repos`、每日热榜 `/trending`、智能推荐 `/recommend`

### 3.2 Service Worker

- install：预缓存 `/`、`/offline.html`、manifest、图标；
- activate：清理旧版本缓存，`clients.claim()`；
- fetch：
  - 非 GET / 跨域 / `/api/*` 直接放行；
  - 导航请求：网络优先，失败回退缓存的页面 → `/` → `/offline.html`；
  - 同源静态资源（`/assets/*`、图片、字体等）：缓存优先 + 网络回填；
- 更新：`updatefound` + `statechange` 后向页面派发 `of:pwa-update-ready`，由 UI 提示刷新。

### 3.3 安装引导与离线状态

- 监听 `beforeinstallprompt`，保存事件并在合适时机调用 `prompt()`；
- iOS Safari 不支持该事件，展示「分享 → 添加到主屏幕」文字指引；
- 用户关闭后写入 localStorage，7 天内不再打扰；
- `online` / `offline` 事件驱动顶部离线提示；
- 新版本就绪时用 sonner toast 提供「立即刷新」操作。

### 3.4 移动端适配

- `index.html`：`viewport-fit=cover`、`apple-mobile-web-app-*`、主题色亮暗两套；
- 底部导航：仪表盘 / 仓库 / 热榜 / 推荐，带 `env(safe-area-inset-bottom)`；
- `Main` 底部留出底部导航高度，避免内容被遮挡；
- 仓库页：桌面表格 + 移动端卡片列表双形态；标题与操作按钮在窄屏纵向排列；
- 热榜列表：窄屏隐藏语言徽章、压缩 Star 列宽、描述两行截断；
- 搜索按钮在窄屏收为图标，配置抽屉在窄屏隐藏，减少头部拥挤。

## 4. 验证

```bash
cd admin && npm run lint && npm run build && npm run test
```

- 新增 `src/lib/pwa.test.ts` 覆盖 standalone / iOS 判定与安装提示冷却；
- 构建产物检查：`dist/manifest.webmanifest`、`dist/sw.js`、`dist/offline.html`、
  `dist/icons/*.png` 均存在；
- 手工检查：Chrome DevTools → Application → Manifest / Service Workers 无错误；
  窄屏 375px 下底部导航、仓库卡片、热榜列表可用。

## 5. 风险与边界

- Cloudflare Pages 的 `_redirects` 需要保证 `/offline.html`、`/sw.js` 等静态文件不被 SPA 回退覆盖；
- SW 缓存策略以 App Shell 为主，不做接口数据缓存，避免展示过期鉴权数据；
- iOS 安装只能依赖系统分享菜单，无法程序化触发，UI 仅做指引；
- 真机安装体验需在 HTTPS 域名（M5-01 部署）后最终验收。
