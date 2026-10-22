"""README 清洗与技术栈启发式提取。

`clean_readme`：去噪（HTML 注释 / 徽章 / 图片 / HTML 标签 / 代码块语言标记 / 多余空行），
为后续摘要与向量化提供干净文本；`extract_tech_stack`：基于关键词表提取技术栈。
"""
from __future__ import annotations

import re

# 常见技术栈关键词（按输出顺序排列，命中即收录）
TECH_KEYWORDS: tuple[str, ...] = (
    "Python", "JavaScript", "TypeScript", "Go", "Golang", "Rust", "Java", "Kotlin",
    "Swift", "C++", "C#", "Ruby", "PHP", "Scala", "Dart", "Elixir", "Lua",
    "Vue", "React", "Next.js", "Nuxt", "Angular", "Svelte", "Flutter", "Electron", "Tauri",
    "Node.js", "Express", "NestJS", "Django", "Flask", "FastAPI", "Spring", "Laravel", "Rails", ".NET",
    "MySQL", "PostgreSQL", "SQLite", "MongoDB", "Redis", "Elasticsearch", "ClickHouse",
    "Kafka", "RabbitMQ", "Nginx", "GraphQL", "gRPC", "WebSocket",
    "Docker", "Kubernetes", "K8s", "Terraform", "Serverless", "DevOps", "CI/CD",
    "TensorFlow", "PyTorch", "Transformers", "LLM", "RAG", "NLP", "机器学习", "深度学习",
    "微服务", "分布式", "中间件", "消息队列", "区块链", "Web3", "爬虫", "小程序", "低代码",
)

_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
# [![alt](badge-img)](target-link) 形式的徽章链接
_BADGE_LINK_RE = re.compile(r"\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)")
# 普通 Markdown 图片 ![alt](url)
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
# HTML 图片与任意 HTML 标签
_HTML_IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
# 代码围栏行：```python / ~~~js → 仅保留围栏符（仅 ASCII 语言标记，且不跨行匹配）
_FENCE_LINE_RE = re.compile(r"^([ \t]*)(?:`{3,}|~{3,})[ \t]*[A-Za-z0-9_.+#-]*[ \t]*$", re.MULTILINE)
_MULTI_BLANK_RE = re.compile(r"\n{3,}")


def clean_readme(md: str) -> str:
    """清洗 README Markdown，返回适合摘要/向量化的纯文本。"""
    if not md:
        return ""
    text = md.replace("\r\n", "\n").replace("\r", "\n")

    text = _HTML_COMMENT_RE.sub("", text)          # 1. HTML 注释
    text = _BADGE_LINK_RE.sub("", text)            # 2. 徽章（先于裸图片，避免残留空链接）
    text = _MD_IMAGE_RE.sub("", text)              # 3. Markdown 图片
    text = _HTML_IMG_RE.sub("", text)              # 4. HTML <img>
    text = _HTML_TAG_RE.sub("", text)              # 5. 其他 HTML 标签（保留标签内文字）
    text = _FENCE_LINE_RE.sub(r"\1```", text)      # 6. 代码围栏去掉语言标记

    # 7. 行尾去空格并折叠连续空行
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = _MULTI_BLANK_RE.sub("\n\n", text)
    return text.strip()


def extract_tech_stack(text: str, max_items: int = 8) -> str:
    """从文本中启发式提取技术栈关键词，返回逗号分隔字符串（最多 max_items 项）。"""
    if not text:
        return ""
    found: list[str] = []
    seen: set[str] = set()
    for keyword in TECH_KEYWORDS:
        if len(found) >= max_items:
            break
        if keyword.isascii():
            # ASCII 关键词使用词边界匹配，避免 "Go" 命中 "Google" 等误报
            pattern = rf"(?<![A-Za-z0-9]){re.escape(keyword)}(?![A-Za-z0-9])"
            matched = re.search(pattern, text, re.IGNORECASE) is not None
        else:
            matched = keyword in text
        key = keyword.lower()
        if matched and key not in seen:
            seen.add(key)
            found.append(keyword)
    return ", ".join(found)
