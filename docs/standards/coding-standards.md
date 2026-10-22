# 编码规范 · Coding Standards

> 规范编号：STD-04 ｜ 适用范围：全部代码 ｜ 维护人：fntp

## 1. 命名约定

| 对象 | 规则 | 示例 |
| --- | --- | --- |
| 目录 / 文件（TS 组件外） | kebab-case | `github-auth-form.tsx`、`sidebar-data.ts` |
| React 组件 | PascalCase（文件与导出同名） | `RecentTrending` |
| 变量 / 函数 | camelCase（TS）、snake_case（Python） | `fetchCurrentUser`、`clean_readme` |
| 常量 | UPPER_SNAKE_CASE | `API_BASE`、`DEFAULT_MAX_AGE` |
| 类型 / 接口 | PascalCase，接口不加 `I` 前缀 | `RepoItem`、`DashboardStats` |
| 布尔值 | `is` / `has` / `should` 前缀 | `isLoading`、`hasKey` |
| 数据库 | 表 snake_case 复数，字段 snake_case | `my_repositories`、`stars_today` |

## 2. 语言与格式

- **TypeScript**：2 空格缩进；单引号；无分号（Prettier 配置为准，admin 目录内以 `.prettierrc` 为准）；
- **Python**：4 空格缩进；遵循 PEP 8；行宽 88（ruff/black 风格）；
- **SQL**：关键字大写；迁移文件一个文件一个目的；
- **Markdown**：标题层级连续；表格对齐；中英文之间不强制空格（团队偏好：加空格更易读）。

## 3. 注释与文档

- 语言：**中文**（专有名词保留英文）；
- 每个模块 / 服务 / 导出函数写明用途；复杂逻辑在「为什么」层面注释，不复述代码；
- 公共 API（edge 路由、vps services、admin api.ts）必须有 JSDoc / docstring；
- TODO 格式：`// TODO(负责人): 内容`。

## 4. 提交信息（Conventional Commits）

```
<type>(<scope>): <中文描述>
```

- type：`feat` `fix` `docs` `style` `refactor` `test` `chore` `ci` `perf`；
- scope：`admin` `edge` `vps` `docs` `repo`；
- 描述用祈使句、一句话、不超 50 字；
- 正文（可选）说明动机与影响；破坏性变更以 `BREAKING CHANGE:` 标注；
- AI 生成的提交在末尾附 `Co-Authored-By: Claude Code <noreply@anthropic.com>`。

## 5. 导入顺序

**TypeScript**：① 外部依赖 → ② `@/` 别名内部模块 → ③ 相对路径；组间空行，组内按字母序。
**Python**：标准库 → 第三方 → 本项目（isort 风格）。

## 6. 错误处理与日志

- 前端：用户可见错误用 `toast`；API 层错误统一经 `apiFetch` 抛出，组件侧降级处理；
- edge：统一 JSON 错误体 `{ "error": "code" }`，不泄漏堆栈；
- vps：`logging` 模块，关键路径 INFO，外部调用失败 WARNING 并降级；禁止 `print`；
- **任何层级都不得输出密钥、token、cookie 值**。

## 7. 测试要求

| 子项目 | 框架 | 最低要求 |
| --- | --- | --- |
| admin | Vitest（浏览器模式） | 新增工具函数 / 状态管理必须带测试 |
| edge | TypeScript 编译检查 | 新增路由通过 `tsc --noEmit` |
| vps | pytest | 新增 service 必须带单测，不访问网络 |

## 8. 样式与 UI（admin）

- 组件优先复用 `src/components/ui/**`（shadcn/ui），不自造轮子；
- 样式一律 Tailwind 原子类；颜色使用主题 token（`text-muted-foreground` 等），不写死色值（图表数据色除外）；
- 界面文案中文；专有名词（GitHub / Star 等）保留原文。
