"""README 清洗与技术栈启发式提取。

`clean_readme`：把 README Markdown 清洗为适合摘要 / 向量化的纯文本——
去除 HTML 注释与脚本块、徽章、图片、HTML 标签、链接地址、引用式定义、
水平分割线与多余空行，并解码 HTML 实体；
`extract_tech_stack`：基于规范化关键词表与别名表提取技术栈，支持
`language` / `topics` 提示、词频与首次出现位置排序。
"""
from __future__ import annotations

import html
import re
from typing import Iterable, Optional

# 技术栈 canonical 名称（同时作为同分时的稳定排序依据）
TECH_KEYWORDS: tuple[str, ...] = (
    "Python", "JavaScript", "TypeScript", "Go", "Rust", "Java", "Kotlin",
    "Swift", "C++", "C#", "Ruby", "PHP", "Scala", "Dart", "Elixir", "Lua",
    "Vue", "React", "Next.js", "Nuxt", "Angular", "Svelte", "Flutter", "Electron", "Tauri",
    "Node.js", "Express", "NestJS", "Django", "Flask", "FastAPI", "Spring", "Laravel", "Rails", ".NET",
    "MySQL", "PostgreSQL", "SQLite", "MongoDB", "Redis", "Elasticsearch", "ClickHouse",
    "Kafka", "RabbitMQ", "Nginx", "GraphQL", "gRPC", "WebSocket",
    "Docker", "Kubernetes", "Terraform", "Serverless", "DevOps", "CI/CD",
    "TensorFlow", "PyTorch", "Transformers", "LLM", "RAG", "NLP", "机器学习", "深度学习",
    "微服务", "分布式", "中间件", "消息队列", "区块链", "Web3", "爬虫", "小程序", "低代码",
)

# canonical → 可识别的别名（全部小写；ASCII 使用词边界，中文按子串）
_TECH_ALIASES: dict[str, tuple[str, ...]] = {
    "Python": ("python", "python3"),
    "JavaScript": ("javascript", "ecmascript"),
    "TypeScript": ("typescript",),
    "Go": ("go", "golang"),
    "Rust": ("rust",),
    "Java": ("java",),
    "Kotlin": ("kotlin",),
    "Swift": ("swift",),
    "C++": ("c++", "cpp"),
    "C#": ("c#", "csharp"),
    "Ruby": ("ruby",),
    "PHP": ("php",),
    "Scala": ("scala",),
    "Dart": ("dart",),
    "Elixir": ("elixir",),
    "Lua": ("lua",),
    "Vue": ("vue", "vue.js", "vuejs"),
    "React": ("react", "react.js", "reactjs"),
    "Next.js": ("next.js", "nextjs"),
    "Nuxt": ("nuxt", "nuxt.js", "nuxtjs"),
    "Angular": ("angular", "angular.js", "angularjs"),
    "Svelte": ("svelte", "sveltekit"),
    "Flutter": ("flutter",),
    "Electron": ("electron",),
    "Tauri": ("tauri",),
    "Node.js": ("node.js", "nodejs", "node"),
    "Express": ("express", "express.js", "expressjs"),
    "NestJS": ("nestjs", "nest.js"),
    "Django": ("django",),
    "Flask": ("flask",),
    "FastAPI": ("fastapi",),
    "Spring": ("spring", "spring boot", "springboot"),
    "Laravel": ("laravel",),
    "Rails": ("rails", "ruby on rails"),
    ".NET": (".net", "dotnet", "asp.net"),
    "MySQL": ("mysql",),
    "PostgreSQL": ("postgresql", "postgres", "pgsql"),
    "SQLite": ("sqlite",),
    "MongoDB": ("mongodb", "mongo"),
    "Redis": ("redis",),
    "Elasticsearch": ("elasticsearch",),
    "ClickHouse": ("clickhouse",),
    "Kafka": ("kafka",),
    "RabbitMQ": ("rabbitmq",),
    "Nginx": ("nginx",),
    "GraphQL": ("graphql",),
    "gRPC": ("grpc",),
    "WebSocket": ("websocket", "websockets"),
    "Docker": ("docker",),
    "Kubernetes": ("kubernetes", "k8s"),
    "Terraform": ("terraform",),
    "Serverless": ("serverless",),
    "DevOps": ("devops",),
    "CI/CD": ("ci/cd", "cicd"),
    "TensorFlow": ("tensorflow",),
    "PyTorch": ("pytorch", "torch"),
    "Transformers": ("transformers", "huggingface"),
    "LLM": ("llm", "大模型"),
    "RAG": ("rag",),
    "NLP": ("nlp",),
    "机器学习": ("机器学习", "machine learning"),
    "深度学习": ("深度学习", "deep learning"),
    "微服务": ("微服务", "microservices"),
    "分布式": ("分布式", "distributed"),
    "中间件": ("中间件",),
    "消息队列": ("消息队列", "message queue"),
    "区块链": ("区块链", "blockchain"),
    "Web3": ("web3",),
    "爬虫": ("爬虫", "crawler", "scraper"),
    "小程序": ("小程序", "mini program"),
    "低代码": ("低代码", "low-code", "low code"),
}

# 常见英文单词与技术名同形：仅匹配首字母大写形式，避免 "go to" / "react to" 误报。
_CASE_SENSITIVE_ALIASES: frozenset[str] = frozenset(
    {"go", "rust", "swift", "dart", "react", "spring", "express", "node", "flask", "torch", "mongo"}
)

_ALIAS_TO_CANONICAL: dict[str, str] = {
    alias: canonical for canonical, aliases in _TECH_ALIASES.items() for alias in aliases
}
for _canonical in TECH_KEYWORDS:
    _ALIAS_TO_CANONICAL.setdefault(_canonical.lower(), _canonical)

_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
# <script> / <style> / <svg> 等整块删除，避免脚本内容混入摘要
_HTML_BLOCK_RE = re.compile(
    r"<(script|style|noscript|svg|template|picture)\b[^>]*>.*?</\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
# 链接 / 图片目标：允许一层嵌套括号（如 image_(1).png）
_INLINE_DEST = r"\((?:[^()]|\([^()]*\))*\)"
# [![alt](badge-img)](target-link)
_BADGE_LINK_RE = re.compile(r"\[!\[[^\]]*\]" + _INLINE_DEST + r"\]" + _INLINE_DEST)
# [![alt][img-id]][link-id]
_BADGE_REF_RE = re.compile(r"\[!\[[^\]]*\]\[[^\]]*\]\]\[[^\]]*\]")
# ![alt](url "title")
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]" + _INLINE_DEST)
# ![alt][img-id] / ![alt][]
_MD_IMAGE_REF_RE = re.compile(r"!\[[^\]]*\]\[[^\]]*\]")
_HTML_IMG_RE = re.compile(r"<img\b[^>]*/?>", re.IGNORECASE)
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_BLOCK_CLOSE_RE = re.compile(
    r"</(?:p|div|li|ul|ol|tr|td|th|h[1-6]|section|article|blockquote|table)\s*>",
    re.IGNORECASE,
)
_HTML_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
# 引用式链接 / 图片定义：[id]: https://...
_REF_DEF_RE = re.compile(r"^[ \t]{0,3}\[[^\]]+\]:[ \t]*\S+.*$", re.MULTILINE)
# [text](url) → text
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]" + _INLINE_DEST)
# [text][id] → text
_MD_REF_LINK_RE = re.compile(r"\[([^\]]+)\]\[[^\]]*\]")
# 代码围栏行：```python / ~~~js → 仅保留围栏符（仅 ASCII 语言标记，且不跨行匹配）
_FENCE_LINE_RE = re.compile(r"^([ \t]*)(?:`{3,}|~{3,})[ \t]*[A-Za-z0-9_.+#-]*[ \t]*$", re.MULTILINE)
# 水平分割线
_HR_RE = re.compile(
    r"^[ \t]{0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$", re.MULTILINE
)
_MULTI_BLANK_RE = re.compile(r"\n{3,}")
_ZERO_WIDTH_RE = re.compile("[\u200b\u200c\u200d\ufeff]")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _alias_pattern(alias: str) -> re.Pattern[str]:
    """构造别名匹配正则：ASCII 使用词边界，中文按子串。"""
    if not alias.isascii():
        return re.compile(re.escape(alias))
    if alias in _CASE_SENSITIVE_ALIASES:
        # 与常见英文单词同形：只匹配首字母大写形式（Go / React / Spring），
        # 避免 "go to" / "react to" / "spring season" 这类误报。
        display = alias[:1].upper() + alias[1:]
        return re.compile(rf"(?<![A-Za-z0-9]){re.escape(display)}(?![A-Za-z])")
    # 前缀禁止字母 / 数字，后缀禁止字母：兼容 "C++17" / "Java8" 这类版本写法
    return re.compile(
        rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z])", re.IGNORECASE
    )


_ALIAS_PATTERNS: dict[str, re.Pattern[str]] = {
    alias: _alias_pattern(alias) for alias in _ALIAS_TO_CANONICAL
}


def _truncate(text: str, max_chars: int) -> str:
    """按段落 / 句末 / 空格边界截断，尽量不切断半个词。"""
    cut = text[:max_chars]
    for separator in ("\n\n", "。", "！", "？", ". ", "! ", "? "):
        index = cut.rfind(separator)
        if index >= int(max_chars * 0.6):
            return cut[: index + len(separator)].rstrip() + "…"
    index = cut.rfind(" ")
    if index > 0:
        cut = cut[:index]
    return cut.rstrip() + "…"


def clean_readme(md: str, *, max_chars: Optional[int] = None) -> str:
    """清洗 README Markdown，返回适合摘要 / 向量化的纯文本。

    - 去除 HTML 注释、脚本 / 样式 / SVG 块、徽章、图片、HTML 标签；
    - Markdown 链接保留锚文本，去掉 URL 与引用式定义；
    - 解码 HTML 实体，折叠多余空行；
    - `max_chars` 可选，按自然边界截断并追加省略号。
    """
    if not md:
        return ""
    if isinstance(md, bytes):  # 兼容调用方传入原始字节
        md = md.decode("utf-8", errors="replace")

    text = str(md).replace("\r\n", "\n").replace("\r", "\n")
    text = text.lstrip("\ufeff")
    text = _ZERO_WIDTH_RE.sub("", text)
    text = _CONTROL_RE.sub("", text)

    text = _HTML_COMMENT_RE.sub("", text)          # 1. HTML 注释
    text = _HTML_BLOCK_RE.sub("", text)            # 2. script / style / svg 等整块
    text = _BADGE_REF_RE.sub("", text)             # 3. 引用式徽章
    text = _BADGE_LINK_RE.sub("", text)            # 4. 内联徽章（先于裸图片）
    text = _MD_IMAGE_REF_RE.sub("", text)          # 5. 引用式图片
    text = _MD_IMAGE_RE.sub("", text)              # 6. Markdown 图片（含标题 / 括号 URL）
    text = _HTML_IMG_RE.sub("", text)              # 7. HTML <img>
    text = _BR_RE.sub("\n", text)                  # 8. <br> → 换行
    text = _BLOCK_CLOSE_RE.sub("\n", text)         # 9. 块级闭合标签 → 换行
    text = _HTML_TAG_RE.sub("", text)              # 10. 其他 HTML 标签（保留标签内文字）
    text = html.unescape(text).replace("\xa0", " ")  # 11. HTML 实体
    text = _REF_DEF_RE.sub("", text)               # 12. 引用式定义
    text = _MD_LINK_RE.sub(r"\1", text)            # 13. [text](url) → text
    text = _MD_REF_LINK_RE.sub(r"\1", text)        # 14. [text][id] → text
    text = _FENCE_LINE_RE.sub(r"\1```", text)      # 15. 代码围栏去掉语言标记
    text = _HR_RE.sub("", text)                    # 16. 水平分割线

    # 17. 行尾去空格并折叠连续空行
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = _MULTI_BLANK_RE.sub("\n\n", text).strip()

    if max_chars and max_chars > 0 and len(text) > max_chars:
        text = _truncate(text, max_chars)
    return text


def _canonical_language(language: Optional[str]) -> str:
    """把语言字段归一为 canonical 名称；未知语言保留原值。"""
    if not language:
        return ""
    raw = str(language).strip()
    if not raw:
        return ""
    key = re.sub(r"\s+", " ", raw.lower())
    return _ALIAS_TO_CANONICAL.get(key, raw)


def _normalize_topics(topics: Optional[Iterable[str]]) -> set[str]:
    """把 topics 归一为小写集合，兼容 `next-js` / `next_js` / `next js`。"""
    normalized: set[str] = set()
    for topic in topics or ():
        key = re.sub(r"\s+", " ", str(topic).strip().lower())
        if not key:
            continue
        normalized.add(key)
        normalized.add(key.replace("-", " "))
        normalized.add(key.replace("_", " "))
        normalized.add(key.replace("-", "").replace("_", ""))
    return normalized


def extract_tech_stack(
    text: str,
    max_items: int = 8,
    *,
    language: Optional[str] = None,
    topics: Optional[Iterable[str]] = None,
) -> str:
    """从文本中启发式提取技术栈关键词，返回逗号分隔字符串（最多 max_items 项）。

    排序优先级：`language` 命中 → `topics` 命中 → 词频 → 首次出现位置。
    别名会归并为 canonical 名称（Golang → Go、k8s → Kubernetes、postgres → PostgreSQL）。
    """
    if max_items <= 0:
        return ""
    text = text or ""
    language_name = _canonical_language(language)
    topic_keys = _normalize_topics(topics)
    canonical_order = {name: index for index, name in enumerate(TECH_KEYWORDS)}
    stats: dict[str, tuple[float, int]] = {}

    for canonical, aliases in _TECH_ALIASES.items():
        count = 0
        first: Optional[int] = None
        for alias in aliases:
            for match in _ALIAS_PATTERNS[alias].finditer(text):
                count += 1
                if first is None or match.start() < first:
                    first = match.start()

        topic_hit = canonical.lower() in topic_keys or any(
            alias in topic_keys for alias in aliases
        )
        is_language = bool(language_name) and canonical == language_name
        if count == 0 and not topic_hit and not is_language:
            continue

        score = count * 10.0
        if first is not None:
            # 越靠前权重略高，但不超过一次词频（10 分）
            score += max(0.0, 5.0 - min(first, 5000) / 1000.0)
        if is_language:
            score += 1000.0
        if topic_hit:
            score += 100.0
        stats[canonical] = (score, first if first is not None else 10**9)

    # 语言字段不在别名表中（如 Jupyter Notebook / HTML）：仍作为技术栈首位输出
    if language_name and language_name not in stats:
        stats[language_name] = (1000.0, -1)

    ranked = sorted(
        stats.items(),
        key=lambda item: (-item[1][0], item[1][1], canonical_order.get(item[0], 999)),
    )
    return ", ".join(name for name, _ in ranked[:max_items])
