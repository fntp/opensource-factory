# M8 验收报告（自动生成）

- 生成时间：2026-10-22T13:45:37+0000
- 分支 / 提交：feat/req-202610-0977-m8-acceptance / 0641ef5
- 运行环境：Linux-6.8.0-138-generic-x86_64-with-glibc2.39 · Python 3.12.3
- 验收方式：跨分支静态资产检查 + M8-04 评估工具实跑 + 缺口登记
- 判定口径：PASS 通过 · FAIL 行为错误 · GAP 未交付缺口（不计入通过率）

## 检查结果

| # | 检查 | 结果 | 说明 | 耗时 |
| --- | --- | --- | --- | --- |
| M8-A01 | M8-01 PWA manifest 与图标 | PASS | icons=['192x192', '512x512'] shortcuts=3 | 0.3ms |
| M8-A02 | M8-01 Service Worker 与离线兜底 | PASS | App Shell 预缓存 / 离线兜底 / /api 排除 / manifest 引用 | 0.2ms |
| M8-A03 | M8-01 安装引导与移动端导航 | PASS | 安装引导 / 离线横幅 / 底部导航 / 安全区 / SW 注册 | 0.3ms |
| M8-B01 | M8-02 MV3 manifest | PASS | MV3 permissions=['activeTab', 'scripting', 'storage'] | 0.4ms |
| M8-B02 | M8-02 扩展核心与单测 | PASS | 仓库解析 / 页面元数据提取 / node:test 用例 | 0.2ms |
| M8-B03 | M8-02 edge 令牌接口与迁移 | PASS | 迁移 0022 / 6 个接口 / CORS / admin 令牌页 | 0.6ms |
| M8-C01 | M8-03 Bot 命令纯函数 | PASS | 命令解析 / HTML 转义 / 3800 分片 / 六类消息 | 0.2ms |
| M8-C02 | M8-03 webhook 路由与迁移 | PASS | 迁移 0021 / 4 个接口 / webhook 免限流 / admin 面板 | 0.5ms |
| M8-D01 | M8-04 评估工具实跑 | PASS | raycast=4.1 shortcuts=3.95 api=0/16 | 36.4ms |
| M8-D02 | M8-04 报告与契约资产 | PASS | 报告 / 契约 / CLI / 测试齐全 | 0.9ms |
| M8-S01 | edge / admin 路由集成 | PASS | edge 路由挂载 + admin 路由树完整 | 0.3ms |
| M8-S02 | M8 迁移编号与 D1 schema | PASS | M8 迁移 0021/0022 编号唯一，D1 schema 同步 | 0.7ms |
| M8-S03 | 需求与验收文档状态 | PASS | backlog 状态正确，验收结论与计划文档齐全 | 1.7ms |
| M8-05-GAP | 开放 API（个人令牌）（平台 pending） | GAP | feat/req-202610-0974-open-api 未合并，需该需求交付后补充验收 | 0.0ms |
| M8-06-GAP | CLI 工具（命令行查询 / 收藏）（平台 pending） | GAP | feat/req-202610-0975-cli-tool 未合并，需该需求交付后补充验收 | 0.0ms |
| M8-07-GAP | 离线可用（PWA 缓存 + 本地数据）（平台 pending） | GAP | feat/req-202610-0976-offline-pwa-local-data 未合并，需该需求交付后补充验收 | 0.0ms |

## 汇总

- PASS：13
- FAIL：0
- GAP：3
- 结论：M8-01~04 已交付能力全部通过；M8-05~07 平台状态仍为 pending，本轮判定为部分验收（有条件通过）
