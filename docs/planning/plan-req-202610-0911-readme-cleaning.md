# 实施计划 · REQ-202610-0911 README 清洗强化

> 需求：REQ-202610-0911（backlog M2-03）｜ 分支：`feat/req-202610-0911-readme-cleaning`
> 目标：在 `vps/app/services/readme.py` 现有基础上强化 README 去噪与技术栈提取，为 M2-04 摘要、M3 向量化提供稳定输入。

## 1. 现状与缺口

`readme.py` 已能去除 HTML 注释、简单徽章 / 图片、HTML 标签与代码围栏语言标记，但存在以下缺口：

1. 徽章 / 图片正则不支持 URL 内括号、标题、引用式写法，GitHub 常见 `<a><img></a>` 徽章块会残留空链接；
2. `<script>` / `<style>` / `<svg>` 等块只删标签不删内容，页面脚本会混入摘要；
3. 未处理 HTML 实体、零宽字符、水平分割线、引用式链接定义与普通 Markdown 链接地址；
4. 技术栈提取仅按固定词表顺序命中，缺少别名归并（Go/Golang、K8s/Kubernetes）、语言字段优先、词频排序与 topics 提示，长 README 中容易被低频噪声占满 8 个名额。

## 2. 方案

### 2.1 `clean_readme(md, *, max_chars=None)`

按固定顺序清洗，保持纯函数、无网络、幂等：

1. 统一换行 / 去 BOM 与零宽字符；
2. 去除 HTML 注释与 `<script>` / `<style>` / `<noscript>` / `<svg>` / `<template>` / `<picture>` 整块；
3. 去除徽章（内联 / 引用式 / HTML 图片）、Markdown 图片（含标题与括号 URL）、引用式图片定义；
4. `<br>` / 块级闭合标签转换为换行，其余 HTML 标签去除、保留标签内文字；
5. 解码 HTML 实体，`&nbsp;` 归一为空格；
6. Markdown 链接保留锚文本、去掉 URL；删除引用式链接定义与水平分割线；
7. 代码围栏仅保留围栏符；逐行去尾空格、折叠连续空行；
8. 可选 `max_chars`：按段落 / 句末 / 空格边界截断并追加省略号，避免截断半个词。

### 2.2 `extract_tech_stack(text, max_items=8, *, language=None, topics=None)`

- 维护 canonical 技术栈词表 + 别名表，输出统一名称（如 `Golang → Go`、`k8s → Kubernetes`、`postgres → PostgreSQL`）；
- ASCII 别名使用词边界匹配，避免 `Go` 命中 `Google`、`Java` 命中 `JavaScript`；中文关键词按子串匹配；
- 排序：`language` 命中强加权 → `topics` 命中加权 → 词频 → 首次出现位置，稳定输出；
- 保持旧调用兼容：`extract_tech_stack(text, 8)` 行为不变，新增参数均为可选。

### 2.3 接入点

- `vps/app/tasks/jobs.py::crawl_trending`：提取时传入 `language`，让热榜语言字段优先进入 `tech_stack`，并把仓库名纳入文本；
- 其余调用方（M1-13 摘要管线、M3 向量化）无需改签名即可获得强化后的清洗结果。

## 3. 文件清单

- `vps/app/services/readme.py`：清洗管线与技术栈提取重写
- `vps/app/tasks/jobs.py`：热榜技术栈提取传入 language
- `vps/tests/test_readme.py`：补充徽章 / 图片 / HTML 块 / 实体 / 截断 / 别名 / 排序用例
- `vps/README.md`、`docs/architecture/overview.md`、`docs/planning/task-planning.md`：行为与状态同步
- 本计划文档

## 4. 验证计划

- `cd vps && .venv/bin/pytest -q`：全部用例通过（含新增 readme 用例）；
- `python -m compileall vps/app`：通过；
- `git diff --check`：无空白错误；
- 纯函数用例覆盖，不访问网络。

## 5. 风险与边界

- 清洗目标是「摘要 / 向量化可读文本」，不追求完整保留 Markdown 结构；代码块内容保留，仅去掉围栏语言标记；
- 技术栈为启发式提取，宁可少报不误报；模型级抽取留待后续需求；
- 本需求不新增数据库字段与接口，不影响 edge / admin 契约。
