# REQ-202610-0934 Email 通道（SMTP）实施计划

- 需求：M4-05 Email 通道（SMTP），依赖 M4-02 站内通知中心；本需求在 VPS 侧独立交付，
  不修改 edge / admin，站内通知中心仍按 M4-02 既有实现工作。
- 分支：`feat/req-202610-0934-email-channel`（基于 `c5728a2`，M4-01 评估链最新基线）。
- 目标：每日把 `pushed` 的高质量推荐渲染为中文摘要邮件，通过 SMTP 投递；
  提供状态查询与测试邮件接口；未启用 / 未配置 / 无数据 / SMTP 异常均安全降级。

## 1. 范围

1. `vps/app/services/email_channel.py`：配置校验、收件人归一化、摘要渲染、
   `smtplib` 发送（STARTTLS / SSL / AUTH / 重试 / 错误脱敏）、幂等与送达记录。
2. `EmailDelivery` 表：每次摘要 / 测试邮件投递落一条记录。
3. 配置：`EMAIL_*` 共 15 项，同步 `runtime.REQUIRED_ENV_KEYS` 与两份 env 模板。
4. 接口：
   - `GET /api/notifications/email/status`
   - `POST /api/notifications/email/test`
   - `POST /api/tasks/send-email-digest`
5. Celery：`send_email_digest` 任务 + beat 每日 09:10（在 09:00 推送准备之后）。
6. 文档与测试。

## 2. 设计要点

- **数据来源**：`recommendations.status='pushed'` 且 `created_at` 落在
  `EMAIL_DIGEST_WINDOW_HOURS` 窗口内，按质量分 / 匹配度排序，最多 `EMAIL_DAILY_LIMIT` 条；
  仓库标题 / 简介 / 技术栈从 `trending_repositories`（回退 `my_repositories`）水合。
- **渲染**：`EmailMessage` multipart（plain + html）；标题与正文全部 HTML 转义，
  邮件头经 `sanitize_header` 去除 CR/LF，防止头注入。
- **发送**：默认 587 + STARTTLS；465 可配 `EMAIL_SSL=true` + `EMAIL_STARTTLS=false`；
  有用户名才登录；瞬时 `SMTPException` / `OSError` 按 `EMAIL_MAX_RETRIES` 指数退避重试；
  认证失败 / 发件人拒绝 / 收件人拒绝不重试。错误信息替换密码与用户名后落库。
- **幂等**：`email:digest:<YYYY-MM-DD>:<排序后的收件人>`；同日同收件人已有 `sent`
  记录则返回 `skipped`，`force=true` 可重发（运营补发 / 排障）。
- **降级**：`EMAIL_ENABLED=false` → `disabled`；缺 host / from / to → `not_configured`；
  无 `pushed` 推荐 → `empty`；SMTP 失败 → `failed` 且写记录，不向 Celery 抛错。
- **安全**：密码只从环境变量读取；状态接口只返回脱敏邮箱与主机 / 端口；
  错误信息替换密码；测试全部使用 fake SMTP，不访问网络。

## 3. 测试计划

`vps/tests/test_email_channel.py`：

- 纯函数：收件人拆分 / 去重 / 非法拒绝、CRLF 头注入、邮箱脱敏、百分比、dedupe key、HTML 转义；
- SMTP：STARTTLS + 登录 + 消息头、瞬时错误重试、认证失败不重试且密码脱敏、配置缺失；
- 服务：disabled / not_configured / empty / sent + 落库 / 同日幂等 / force / 失败落库 /
  窗口与条数限制 / 测试邮件 / 状态脱敏；
- API：status 200、test 409（未启用）、test 200、内部 token 401、任务入队 202；
- 任务：`send_email_digest` 成功返回 sent。

## 4. 验收与上线

1. `bacs-heavy` 执行 `vps/.venv/bin/pytest -q`（全量）与 `compileall`；
2. 在 `.env` 配置 SMTP 服务商、发件人、收件人后，用
   `POST /api/notifications/email/test` 验证连通性；
3. 确认 09:00 `daily_push` 已产生 `pushed` 推荐，09:10 自动发送；或手动
   `POST /api/tasks/send-email-digest` 触发；
4. 查看 `GET /api/notifications/email/status` 的 `lastDelivery` 确认送达状态。

## 5. 风险与待确认

- SMTP 服务商、发件人域名、端口 / TLS 组合需人工按实际服务商配置，见
  `docs/requirements/open-questions.md` Q15；
- 当前为单节点串行发送，收件人上限 20；多用户个性化收件人需后续推送偏好设置（M4-06）承接；
- `EmailDelivery` 暂无自动清理策略，后续可随 M4-08 推送记录一起归档。
