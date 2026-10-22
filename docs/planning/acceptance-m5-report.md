# M5 验收报告（自动生成）

- 生成时间：2026-10-22T10:19:21+0000
- 分支 / 提交：feat/req-202610-0947-m5-acceptance / 787c24c
- 运行环境：Linux-6.8.0-138-generic-x86_64-with-glibc2.39 · Python 3.12.3
- 验收方式：临时 SQLite + 临时运行目录 + 真实 uvicorn + 部署资产 dry-run
- 判定口径：PASS 通过 · FAIL 行为错误 · SKIP 跳过

## 检查结果

| # | 检查 | 结果 | 说明 | 耗时 |
| --- | --- | --- | --- | --- |
| M5-A01 | 部署脚本齐全且可执行 | PASS | 19 个部署脚本齐全且可执行 | 0.9ms |
| M5-A02 | 部署脚本语法检查 | PASS | 19 个脚本 bash -n 通过 | 70.6ms |
| M5-A03 | systemd 单元资源与安全基线 | PASS | 4 个 systemd 单元基线齐全（MemoryMax / NoNewPrivileges / 环境文件） | 1.3ms |
| M5-A04 | 部署模板占位符与安全约束 | PASS | wrangler / Caddy 模板占位符与安全约束齐全 | 0.8ms |
| M5-A05 | 配置渲染（wrangler / Caddy） | PASS | wrangler + Caddy 渲染无残留占位符，产物权限 600 | 40.5ms |
| M5-A06 | preflight / smoke-test dry-run | PASS | preflight / smoke-test dry-run 通过 | 75.3ms |
| M5-A07 | 部署工作流门禁 | PASS | 部署工作流受 DEPLOY_ENABLED 门禁保护且串行 | 0.2ms |
| M5-G01 | 运维手册与指南齐全 | PASS | 7 份运维指南齐全，runbook 关键章节完整 | 0.7ms |
| M5-G02 | 运维脚本帮助可用 | PASS | ops-diagnose / resource-budget / local-allinone 帮助可用 | 157.4ms |
| M5-I01 | 三端版本号 1.0.0 | PASS | admin / edge / vps / 两份环境模板均为 1.0.0 | 1.1ms |
| M5-I02 | v1.0 发布说明 | PASS | 发布说明包含版本、已知限制与回滚说明 | 0.1ms |
| M5-B01 | 默认模式关闭本机接口 | PASS | LOCAL_MODE=0 时 /local/api/* 全部 404 | 13.6ms |
| M5-C01 | 健康检查 / 就绪探针 | PASS | healthz + ready 均 200 | 7.1ms |
| M5-C02 | 监控实时状态 | PASS | status=ok，5 项健康检查 | 49.7ms |
| M5-C03 | 监控检查与历史落库 | PASS | 检查 48d65acf 落库，历史 1 条 | 35.6ms |
| M5-C04 | 告警列表与确认 | PASS | 告警 accept-b1bda4784589 确认成功 | 40.7ms |
| M5-C05 | 日志状态与保留清理 | PASS | 日志目录 1 个文件 / 0.0 MB | 9.4ms |
| M5-D01 | SQLite 快照创建与预算 | PASS | 快照 sqlite-20261022T101917Z.sqlite3.gz（6184 bytes） | 25.9ms |
| M5-D02 | 快照完整性校验 | PASS | 5 项校验通过，21 张表 | 11.8ms |
| M5-D03 | 恢复演练 | PASS | 恢复到临时库成功，21 张表行数一致 | 24.9ms |
| M5-D04 | 备份产物列表 | PASS | 1 份 SQLite 备份 | 4.3ms |
| M5-E01 | 安全加固状态 | PASS | 双令牌轮换状态正确，限流参数可见，无明文泄露 | 3.5ms |
| M5-E02 | 内部令牌双令牌与 401 | PASS | 旧令牌可用，错误令牌 401 | 8.7ms |
| M5-E03 | 接口限流 429 | PASS | 限流触发 429，Retry-After=60 | 18.5ms |
| M5-E04 | 安全响应头 | PASS | 安全响应头基线齐全 | 2.2ms |
| M5-B02 | 本机静态托管与 SPA 回退 | PASS | 首页与 SPA 回退均命中 admin 构建产物 | 32.7ms |
| M5-B03 | 本机只读 API 契约 | PASS | 用户 m5-local / 仓库 1 个 / 版本 1.0.0 | 71.5ms |
| M5-F01 | 资源预算 4G / 15G 判定 | PASS | PASS：内存 43.7 / 4096 MB，磁盘 593.4 / 15360 MB | 457.8ms |
| M5-H01 | 安全审计无 critical / high | PASS | status=WARN，medium=2，checks=7 | 870.3ms |

## 汇总

- PASS：29
- FAIL：0
- SKIP：0
- 结论：全部通过，可发布 v1.0.0
