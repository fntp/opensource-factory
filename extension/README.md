# OpenFactory 收藏助手（浏览器扩展）

在 GitHub / Gitee 仓库页面一键收藏到 OpenFactory「我的仓库」。Manifest V3、零构建、原生 ES Module。

## 功能

- 弹窗预览当前仓库的 owner/repo、简介、语言、Star / Fork 数；
- 一键收藏，重复收藏会更新描述与计数；
- 快捷键 `Ctrl+Shift+O`（macOS `Command+Shift+O`）收藏当前页面；
- 已收藏状态检测（不会把其他用户收藏的仓库误判为「已收藏」）；
- 令牌只保存在本机 `chrome.storage.local`，网络请求由 background 发起，不进入页面上下文。

## 安装（开发者模式）

1. 打开 `chrome://extensions`（Edge 为 `edge://extensions`），开启「开发者模式」。
2. 点击「加载已解压的扩展程序」，选择本目录 `extension/`。
3. 首次安装会自动打开设置页；也可以在扩展详情中点「扩展程序选项」。

Firefox 需在 `about:debugging#/runtime/this-firefox` 中临时载入 `manifest.json`（Firefox 对 MV3 `optional_host_permissions` 的支持以当前版本为准）。

## 配置

1. 登录 OpenFactory 站点，进入「设置 → 浏览器扩展」。
2. 点击「创建令牌」，复制形如 `ofx_…` 的令牌（只显示一次）。
3. 在扩展设置页填写 API 地址（站点根地址，如 `https://of.example.com`）与令牌，点击「保存并测试连接」。
4. 按提示授予该站点的访问权限。

> 令牌只保存 SHA-256 摘要，服务端无法找回明文；遗失后请撤销并重新创建。

## 目录结构

```
extension/
├── manifest.json          # MV3 清单：权限、快捷键、入口
├── icons/                 # 16/32/48/128 图标
├── src/
│   ├── background.js      # Service Worker：配置读取、Bearer 请求、快捷键
│   ├── popup.html/.css/.js# 弹窗：仓库预览与收藏
│   ├── options.html/.css/.js # 设置页：API 地址、令牌、站点权限
│   ├── content/extract.js # 注入页面的仓库元数据提取器
│   └── lib/repo.js        # 纯函数：URL 解析、计数、payload、校验
└── tests/repo.test.mjs    # node:test 单元测试
```

## 开发与测试

```bash
cd extension
npm test        # node --test tests/*.test.mjs，无需安装依赖
```

修改扩展代码后，在 `chrome://extensions` 点击扩展卡片上的刷新按钮；修改 background 后需重新加载扩展。

## 权限说明

| 权限 | 用途 |
| --- | --- |
| `activeTab` | 用户点击图标 / 快捷键时临时读取当前标签页 |
| `scripting` | 注入 `extractRepoPage` 读取仓库页可见信息 |
| `storage` | 保存 API 地址与扩展令牌 |
| `optional_host_permissions` | 仅在用户保存站点地址时申请该站点访问权限 |

扩展不会读取浏览历史、Cookie 或其他标签页内容，也不会上传仓库页之外的任何数据。

## 故障排查

| 现象 | 处理 |
| --- | --- |
| 提示「先连接你的 OpenFactory」 | 打开设置页填写 API 地址与令牌 |
| 连接测试 401 | 令牌无效或已撤销，在站点重新创建 |
| 连接测试网络错误 | 检查 API 地址、站点是否可访问、是否授予站点权限 |
| 当前页面不是仓库页 | 仅支持 `github.com/{owner}/{repo}` 与 `gitee.com/{owner}/{repo}` |
| 收藏返回 409 | 该仓库已被其他用户收藏，当前数据模型下不转移归属 |
| 快捷键无反应 | 在 `chrome://extensions/shortcuts` 检查是否与其他扩展冲突 |
