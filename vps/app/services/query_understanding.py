"""查询理解：同义词扩展与技术栈词表归一化（M3-10）。

在不引入 LLM、不访问网络的前提下，把用户的自然语言查询归一化为
「原查询 + 规范技术栈词 + 同义词扩展」，供两处复用：

- 语义检索：`rewritten` 交给 `EmbeddingService` 编码（`/api/search/embed` / `query` / `semantic`）；
- 关键词降级：`keywordTerms` 交给 edge 做 D1 多词 OR LIKE（VPS 不可达时仍用原查询）。

设计原则：

1. **纯规则、确定性**：词表内置，匹配结果与运行环境无关；
2. **原查询优先**：`rewritten` 始终以原查询开头，扩展词去重后追加；
3. **长词优先**：同一位置命中多个别名时保留更长的词条（`react native` 优先于 `react`）；
4. **ASCII 词边界**：避免 `Go` 命中 `Google`、`Java` 命中 `JavaScript`；
5. **未命中即原样返回**：无词表命中时行为与 M3-04 完全一致。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from app.config import get_settings

MAX_KEYWORD_TERMS = 8
DEFAULT_MAX_TERMS = 12
_MAX_TERMS_LIMIT = 50


class QueryUnderstandingError(ValueError):
    """查询为空或词表参数非法。"""


@dataclass(frozen=True)
class VocabularyEntry:
    """一条词表：规范名 + 别名 + 扩展词（kind=tech|concept）。"""

    canonical: str
    aliases: tuple[str, ...]
    expansions: tuple[str, ...] = ()
    kind: str = "tech"


@dataclass(frozen=True)
class QueryUnderstanding:
    """查询理解结果（可直接序列化为 camelCase 响应）。"""

    query: str
    rewritten: str
    expanded: bool
    tech_stack: tuple[str, ...]
    concepts: tuple[str, ...]
    terms: tuple[str, ...]
    keyword_terms: tuple[str, ...]
    max_terms: int

    def to_dict(self) -> dict[str, object]:
        return {
            "query": self.query,
            "rewritten": self.rewritten,
            "expanded": self.expanded,
            "techStack": list(self.tech_stack),
            "concepts": list(self.concepts),
            "terms": list(self.terms),
            "keywordTerms": list(self.keyword_terms),
            "maxTerms": self.max_terms,
        }


# ---------------------------------------------------------------------------
# 词表
# ---------------------------------------------------------------------------

TECH_VOCAB: tuple[VocabularyEntry, ...] = (
    # 语言
    VocabularyEntry("Python", ("python", "python3", "py")),
    VocabularyEntry("JavaScript", ("javascript", "js", "ecmascript", "es6")),
    VocabularyEntry("TypeScript", ("typescript", "ts")),
    VocabularyEntry("Go", ("golang", "go语言", "go 语言", "go lang")),
    VocabularyEntry("Rust", ("rust", "rustlang")),
    VocabularyEntry("Java", ("java",)),
    VocabularyEntry("Kotlin", ("kotlin",)),
    VocabularyEntry("Swift", ("swift",)),
    VocabularyEntry("C++", ("c++", "cpp")),
    VocabularyEntry("C#", ("c#", "csharp")),
    VocabularyEntry("Ruby", ("ruby",)),
    VocabularyEntry("PHP", ("php",)),
    VocabularyEntry("Scala", ("scala",)),
    VocabularyEntry("Dart", ("dart",)),
    VocabularyEntry("Elixir", ("elixir",)),
    VocabularyEntry("Lua", ("lua",)),
    # 前端 / 客户端
    VocabularyEntry("React", ("react", "reactjs", "react.js"), ("frontend",)),
    VocabularyEntry("Vue", ("vue", "vuejs", "vue.js", "vue3"), ("frontend",)),
    VocabularyEntry("Angular", ("angular", "angularjs"), ("frontend",)),
    VocabularyEntry("Svelte", ("svelte", "sveltekit"), ("frontend",)),
    VocabularyEntry("Next.js", ("next.js", "nextjs"), ("react", "frontend")),
    VocabularyEntry("Nuxt", ("nuxt", "nuxt.js", "nuxtjs"), ("vue", "frontend")),
    VocabularyEntry("React Native", ("react native", "react-native"), ("mobile", "cross-platform")),
    VocabularyEntry("Flutter", ("flutter",), ("mobile", "cross-platform")),
    VocabularyEntry("Electron", ("electron",), ("desktop",)),
    VocabularyEntry("Tauri", ("tauri",), ("desktop",)),
    VocabularyEntry("Tailwind CSS", ("tailwind", "tailwindcss", "tailwind css"), ("css",)),
    # 后端框架
    VocabularyEntry("Node.js", ("node.js", "nodejs", "node"), ("backend",)),
    VocabularyEntry("NestJS", ("nestjs", "nest.js"), ("node.js", "backend")),
    VocabularyEntry("Express", ("expressjs", "express"), ("node.js", "backend")),
    VocabularyEntry("Django", ("django",), ("python", "backend")),
    VocabularyEntry("Flask", ("flask",), ("python", "backend")),
    VocabularyEntry("FastAPI", ("fastapi",), ("python", "backend")),
    VocabularyEntry("Spring", ("spring boot", "springboot", "spring"), ("java", "backend")),
    VocabularyEntry("Laravel", ("laravel",), ("php", "backend")),
    VocabularyEntry("Rails", ("ruby on rails", "rails"), ("ruby", "backend")),
    VocabularyEntry(".NET", (".net", "dotnet", "asp.net"), ("c#", "backend")),
    # 数据 / 中间件
    VocabularyEntry("PostgreSQL", ("postgresql", "postgres", "pgsql", "pg"), ("relational database",)),
    VocabularyEntry("MySQL", ("mysql",), ("relational database",)),
    VocabularyEntry("SQLite", ("sqlite",), ("embedded database",)),
    VocabularyEntry("MongoDB", ("mongodb", "mongo"), ("nosql",)),
    VocabularyEntry("Redis", ("redis",), ("cache",)),
    VocabularyEntry("Elasticsearch", ("elasticsearch", "elastic search"), ("full-text search",)),
    VocabularyEntry("ClickHouse", ("clickhouse",), ("analytics database",)),
    VocabularyEntry("Kafka", ("kafka",), ("message queue", "event streaming")),
    VocabularyEntry("RabbitMQ", ("rabbitmq",), ("message queue",)),
    VocabularyEntry("GraphQL", ("graphql",), ("api",)),
    VocabularyEntry("gRPC", ("grpc",), ("rpc", "api")),
    VocabularyEntry("WebSocket", ("websocket", "websockets"), ("realtime",)),
    # 部署 / 运维
    VocabularyEntry("Docker", ("docker",), ("container", "containerization")),
    VocabularyEntry(
        "Kubernetes",
        ("kubernetes", "k8s", "kube", "k8s集群", "k8s 集群"),
        ("container orchestration", "cloud native"),
    ),
    VocabularyEntry("Terraform", ("terraform",), ("infrastructure as code",)),
    VocabularyEntry("Nginx", ("nginx",), ("reverse proxy",)),
    VocabularyEntry("Serverless", ("serverless", "无服务器"), ("cloud functions",)),
    VocabularyEntry("CI/CD", ("ci/cd", "cicd", "持续集成", "持续部署"), ("continuous integration", "continuous delivery")),
    VocabularyEntry("DevOps", ("devops",), ("ci/cd", "automation")),
    # AI / 数据
    VocabularyEntry("PyTorch", ("pytorch", "torch"), ("deep learning",)),
    VocabularyEntry("TensorFlow", ("tensorflow",), ("deep learning",)),
    VocabularyEntry("Transformers", ("transformers", "huggingface", "hugging face"), ("nlp", "pretrained model")),
    VocabularyEntry(
        "LLM",
        ("llm", "大模型", "大语言模型", "large language model"),
        ("large language model", "generative ai"),
    ),
    VocabularyEntry("RAG", ("rag", "检索增强", "检索增强生成"), ("retrieval augmented generation", "vector search")),
    VocabularyEntry("NLP", ("nlp", "自然语言处理"), ("natural language processing",)),
    VocabularyEntry("机器学习", ("机器学习", "machine learning", "ml"), ("machine learning", "model training")),
    VocabularyEntry("深度学习", ("深度学习", "deep learning"), ("deep learning", "neural network")),
    VocabularyEntry(
        "向量数据库",
        ("向量数据库", "vector database", "vector db"),
        ("vector database", "embedding", "similarity search"),
    ),
)

CONCEPT_SYNONYMS: tuple[VocabularyEntry, ...] = (
    VocabularyEntry(
        "管理后台",
        ("管理后台", "后台管理", "后台", "admin panel", "admin dashboard", "admin"),
        ("admin", "dashboard", "management console"),
        kind="concept",
    ),
    VocabularyEntry(
        "脚手架",
        ("脚手架", "模板", "样板", "starter kit", "starter", "boilerplate", "template"),
        ("boilerplate", "starter kit", "template"),
        kind="concept",
    ),
    VocabularyEntry(
        "组件库",
        ("组件库", "ui 库", "ui库", "component library"),
        ("component library", "ui kit", "design system"),
        kind="concept",
    ),
    VocabularyEntry(
        "可视化",
        ("可视化", "图表", "看板", "visualization", "charts", "dashboard"),
        ("visualization", "charts", "dashboard"),
        kind="concept",
    ),
    VocabularyEntry(
        "任务调度",
        ("任务调度", "定时任务", "调度器", "scheduler", "cron"),
        ("scheduler", "cron", "task queue"),
        kind="concept",
    ),
    VocabularyEntry(
        "富文本",
        ("富文本", "富文本编辑器", "rich text", "wysiwyg"),
        ("rich text editor", "wysiwyg"),
        kind="concept",
    ),
    VocabularyEntry(
        "实时协作",
        ("实时协作", "协同编辑", "多人协作", "realtime collaboration", "collaboration"),
        ("realtime collaboration", "crdt", "websocket"),
        kind="concept",
    ),
    VocabularyEntry(
        "多租户",
        ("多租户", "multi-tenant", "multitenant", "tenant isolation"),
        ("multi-tenant", "saas", "tenant isolation"),
        kind="concept",
    ),
    VocabularyEntry(
        "支付",
        ("支付", "计费", "payment", "billing"),
        ("payment", "billing", "checkout"),
        kind="concept",
    ),
    VocabularyEntry(
        "权限",
        ("权限", "鉴权", "rbac", "authorization"),
        ("rbac", "authorization", "access control"),
        kind="concept",
    ),
    VocabularyEntry(
        "搜索",
        ("搜索", "检索", "search", "full-text search"),
        ("search", "full-text search", "indexing"),
        kind="concept",
    ),
    VocabularyEntry(
        "监控",
        ("监控", "可观测", "monitoring", "observability"),
        ("monitoring", "observability", "metrics"),
        kind="concept",
    ),
    VocabularyEntry("日志", ("日志", "logging"), ("logging", "log aggregation"), kind="concept"),
    VocabularyEntry("网关", ("网关", "api gateway", "gateway"), ("gateway", "api gateway", "reverse proxy"), kind="concept"),
    VocabularyEntry("缓存", ("缓存", "cache", "caching"), ("cache", "caching", "redis"), kind="concept"),
    VocabularyEntry(
        "消息队列",
        ("消息队列", "message queue", "mq"),
        ("message queue", "kafka", "rabbitmq"),
        kind="concept",
    ),
    VocabularyEntry(
        "微服务",
        ("微服务", "microservice", "microservices"),
        ("microservices", "service mesh"),
        kind="concept",
    ),
    VocabularyEntry("全栈", ("全栈", "full-stack", "fullstack"), ("full-stack", "frontend", "backend"), kind="concept"),
    VocabularyEntry("前端", ("前端", "frontend", "front-end"), ("frontend", "ui"), kind="concept"),
    VocabularyEntry("后端", ("后端", "服务端", "backend", "back-end"), ("backend", "server"), kind="concept"),
    VocabularyEntry("移动端", ("移动端", "移动应用", "mobile app", "mobile"), ("mobile", "ios", "android"), kind="concept"),
    VocabularyEntry("桌面端", ("桌面端", "桌面应用", "desktop app", "desktop"), ("desktop", "electron", "tauri"), kind="concept"),
    VocabularyEntry(
        "命令行",
        ("命令行", "cli", "command line", "terminal"),
        ("cli", "command line", "terminal"),
        kind="concept",
    ),
    VocabularyEntry(
        "爬虫",
        ("爬虫", "抓取", "采集", "crawler", "scraping", "scraper"),
        ("crawler", "scraping", "spider"),
        kind="concept",
    ),
    VocabularyEntry("低代码", ("低代码", "low-code", "lowcode"), ("low-code", "no-code", "visual builder"), kind="concept"),
    VocabularyEntry(
        "推荐系统",
        ("推荐系统", "推荐引擎", "recommendation system", "recommender"),
        ("recommendation", "recommender system", "ranking"),
        kind="concept",
    ),
    VocabularyEntry("工作流", ("工作流", "workflow", "编排"), ("workflow", "orchestration", "automation"), kind="concept"),
    VocabularyEntry("自动化", ("自动化", "automation"), ("automation", "automated"), kind="concept"),
    VocabularyEntry("部署", ("部署", "deployment", "deploy"), ("deployment", "devops", "ci/cd"), kind="concept"),
    VocabularyEntry("容器化", ("容器化", "containerization"), ("container", "docker", "kubernetes"), kind="concept"),
    VocabularyEntry("插件", ("插件", "plugin", "extension"), ("plugin", "extension", "addon"), kind="concept"),
    VocabularyEntry("博客", ("博客", "blog", "cms"), ("blog", "cms", "content management"), kind="concept"),
    VocabularyEntry(
        "电商",
        ("电商", "电子商务", "ecommerce", "e-commerce"),
        ("ecommerce", "shopping cart", "payment"),
        kind="concept",
    ),
    VocabularyEntry("社交", ("社交", "social", "community"), ("social", "community", "feed"), kind="concept"),
    VocabularyEntry("教育", ("教育", "课程", "education", "e-learning"), ("education", "e-learning", "lms"), kind="concept"),
    VocabularyEntry("金融", ("金融", "fintech", "finance"), ("finance", "fintech", "trading"), kind="concept"),
    VocabularyEntry("游戏", ("游戏", "game", "gaming"), ("game", "gaming", "engine"), kind="concept"),
    VocabularyEntry(
        "音视频",
        ("音视频", "视频", "音频", "audio", "video", "streaming"),
        ("audio", "video", "streaming"),
        kind="concept",
    ),
    VocabularyEntry(
        "图片处理",
        ("图片处理", "图像处理", "image processing", "image"),
        ("image processing", "image", "vision"),
        kind="concept",
    ),
    VocabularyEntry(
        "文件管理",
        ("文件管理", "网盘", "file manager", "file storage"),
        ("file management", "storage", "upload"),
        kind="concept",
    ),
    VocabularyEntry("聊天", ("聊天", "即时通讯", "chat", "messaging"), ("chat", "messaging", "realtime"), kind="concept"),
    VocabularyEntry(
        "客服",
        ("客服", "customer service", "support ticket"),
        ("customer service", "support", "ticket"),
        kind="concept",
    ),
    VocabularyEntry(
        "数据分析",
        ("数据分析", "analytics", "data analysis"),
        ("analytics", "data analysis", "reporting"),
        kind="concept",
    ),
    VocabularyEntry("报表", ("报表", "report", "reporting"), ("report", "reporting", "dashboard"), kind="concept"),
    VocabularyEntry(
        "单点登录",
        ("单点登录", "sso", "single sign-on"),
        ("sso", "single sign-on", "oauth"),
        kind="concept",
    ),
    VocabularyEntry(
        "认证",
        ("认证", "登录", "authentication", "oauth", "login"),
        ("authentication", "oauth", "login"),
        kind="concept",
    ),
    VocabularyEntry(
        "国际化",
        ("国际化", "i18n", "internationalization"),
        ("i18n", "internationalization", "localization"),
        kind="concept",
    ),
    VocabularyEntry(
        "跨平台",
        ("跨平台", "cross-platform", "cross platform"),
        ("cross-platform", "desktop", "mobile"),
        kind="concept",
    ),
    VocabularyEntry(
        "微前端",
        ("微前端", "micro frontend", "microfrontend"),
        ("micro frontend", "module federation"),
        kind="concept",
    ),
    VocabularyEntry("主题", ("主题", "theme", "theming"), ("theme", "theming", "design system"), kind="concept"),
    VocabularyEntry("开源", ("开源", "open source", "opensource"), ("open source", "oss"), kind="concept"),
    VocabularyEntry("工具", ("工具", "toolkit", "utility"), ("tool", "utility", "toolkit"), kind="concept"),
    VocabularyEntry("数据库", ("数据库", "database"), ("database", "sql", "storage"), kind="concept"),
    VocabularyEntry("API", ("api", "接口", "restful", "rest"), ("api", "rest", "http"), kind="concept"),
    VocabularyEntry("SDK", ("sdk", "客户端库", "client library"), ("sdk", "client library"), kind="concept"),
)

_ALL_ENTRIES: tuple[VocabularyEntry, ...] = (*TECH_VOCAB, *CONCEPT_SYNONYMS)


def _is_ascii(value: str) -> bool:
    return all(ord(char) < 128 for char in value)


def _alias_pattern(alias: str) -> re.Pattern[str]:
    """ASCII 别名使用前后非字母数字边界，避免子串误命中。"""
    return re.compile(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])")


@dataclass(frozen=True)
class _Match:
    start: int
    end: int
    entry: VocabularyEntry


_ALIAS_INDEX: tuple[tuple[str, VocabularyEntry, Optional[re.Pattern[str]]], ...] = tuple(
    (alias.casefold(), entry, _alias_pattern(alias.casefold()) if _is_ascii(alias) else None)
    for entry in _ALL_ENTRIES
    for alias in entry.aliases
)


def _find_matches(text: str) -> list[_Match]:
    """在归一化文本中查找词表命中，长词优先并消除重叠。"""
    matches: list[_Match] = []
    for alias, entry, pattern in _ALIAS_INDEX:
        if pattern is not None:
            matches.extend(
                _Match(match.start(), match.end(), entry) for match in pattern.finditer(text)
            )
            continue
        start = text.find(alias)
        while start != -1:
            matches.append(_Match(start, start + len(alias), entry))
            start = text.find(alias, start + len(alias))

    # 同一位置优先保留更长的别名；随后按出现位置排序。
    matches.sort(key=lambda item: (item.start, -(item.end - item.start)))
    kept: list[_Match] = []
    occupied: list[tuple[int, int]] = []
    for match in matches:
        if any(match.start < end and match.end > start for start, end in occupied):
            continue
        kept.append(match)
        occupied.append((match.start, match.end))

    # 同一词条只保留第一次命中，避免重复扩展。
    unique: list[_Match] = []
    seen: set[tuple[str, str]] = set()
    for match in kept:
        key = (match.entry.kind, match.entry.canonical.casefold())
        if key in seen:
            continue
        seen.add(key)
        unique.append(match)
    return unique


def _term_present(text: str, term: str) -> bool:
    """判断扩展词是否已在查询中出现（ASCII 用词边界，中文用子串）。"""
    if not term:
        return True
    folded = term.casefold()
    if _is_ascii(term):
        return _alias_pattern(folded).search(text) is not None
    return folded in text


def _dedupe(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return tuple(result)


def understand_query(
    query: str,
    *,
    enabled: Optional[bool] = None,
    max_terms: Optional[int] = None,
) -> QueryUnderstanding:
    """解析查询并返回同义词 / 技术栈扩展结果。"""
    normalized = " ".join((query or "").split())
    if not normalized:
        raise QueryUnderstandingError("查询不能为空")

    if enabled is None or max_terms is None:
        settings = get_settings()
        if enabled is None:
            enabled = settings.SEARCH_QUERY_EXPANSION_ENABLED
        if max_terms is None:
            max_terms = settings.SEARCH_QUERY_EXPANSION_MAX_TERMS

    limit = max(1, min(_MAX_TERMS_LIMIT, int(max_terms)))
    folded_query = normalized.casefold()

    if not enabled:
        return QueryUnderstanding(
            query=normalized,
            rewritten=normalized,
            expanded=False,
            tech_stack=(),
            concepts=(),
            terms=(),
            keyword_terms=(normalized,),
            max_terms=limit,
        )

    matches = _find_matches(folded_query)
    if not matches:
        return QueryUnderstanding(
            query=normalized,
            rewritten=normalized,
            expanded=False,
            tech_stack=(),
            concepts=(),
            terms=(),
            keyword_terms=(normalized,),
            max_terms=limit,
        )

    tech_stack: list[str] = []
    concepts: list[str] = []
    terms: list[str] = []
    seen_terms: set[str] = set()

    for match in matches:
        entry = match.entry
        if entry.kind == "tech":
            tech_stack.append(entry.canonical)
        else:
            concepts.append(entry.canonical)

        for candidate in (entry.canonical, *entry.expansions):
            key = candidate.casefold()
            if key in seen_terms:
                continue
            seen_terms.add(key)
            if _term_present(folded_query, candidate):
                continue
            terms.append(candidate)
            if len(terms) >= limit:
                break
        if len(terms) >= limit:
            break

    keyword_terms = list(_dedupe([normalized, *terms]))[:MAX_KEYWORD_TERMS]
    return QueryUnderstanding(
        query=normalized,
        rewritten=" ".join([normalized, *terms]) if terms else normalized,
        expanded=bool(terms),
        tech_stack=_dedupe(tech_stack),
        concepts=_dedupe(concepts),
        terms=tuple(terms),
        keyword_terms=tuple(keyword_terms),
        max_terms=limit,
    )


def vocabulary_stats() -> dict[str, int]:
    """词表规模（供 `/api/search/status` 观测）。"""
    aliases = {alias.casefold() for entry in _ALL_ENTRIES for alias in entry.aliases}
    return {
        "techEntries": len(TECH_VOCAB),
        "conceptEntries": len(CONCEPT_SYNONYMS),
        "aliases": len(aliases),
    }
