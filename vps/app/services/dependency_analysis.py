"""依赖分析（M6-07 / REQ-202610-0954）。

把个人收藏仓库的依赖清单解析为结构化依赖，并与仓库语言（技术栈）关联：

- **解析**：npm / PyPI / Go / Cargo / Maven / RubyGems / Composer 常见清单，
  全部为纯函数，异常文本返回空列表而不抛错；
- **扫描**：按仓库拉取候选清单（GitHub raw），覆盖式写入 `repo_dependencies`，
  单仓库失败只标记 `failed`，不阻断整批；
- **聚合**：只读本地表，输出技术栈分布、生态构成、依赖覆盖率与「依赖 × 语言」关联。

测试通过 `fetcher` 注入离线清单，不访问网络。
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Optional

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import MyRepository, RepoDependency, RepoDependencyScan

logger = logging.getLogger(__name__)

ECOSYSTEMS: tuple[str, ...] = ("npm", "pypi", "go", "cargo", "maven", "rubygems", "composer")

# 候选清单：文件名 → 生态。顺序即扫描顺序，命中多个时全部解析。
MANIFESTS: tuple[tuple[str, str], ...] = (
    ("package.json", "npm"),
    ("requirements.txt", "pypi"),
    ("pyproject.toml", "pypi"),
    ("go.mod", "go"),
    ("Cargo.toml", "cargo"),
    ("pom.xml", "maven"),
    ("Gemfile", "rubygems"),
    ("composer.json", "composer"),
)

MANIFEST_ECOSYSTEM = dict(MANIFESTS)

RAW_BASE = "https://raw.githubusercontent.com"


class DependencyError(Exception):
    """依赖分析业务异常。"""


class DependencyFetchError(DependencyError):
    """清单拉取失败（网络 / 非 404 状态码）。"""


@dataclass(frozen=True)
class Dependency:
    """解析后的单条依赖。"""

    ecosystem: str
    name: str
    version: Optional[str] = None
    kind: str = "runtime"
    manifest: str = ""

    def as_dict(self) -> dict[str, Optional[str]]:
        return {
            "ecosystem": self.ecosystem,
            "name": self.name,
            "version": self.version,
            "kind": self.kind,
            "manifest": self.manifest,
        }


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_name(ecosystem: str, name: str) -> str:
    """规范化依赖名：PyPI 小写并把 `_` / `.` 归一为 `-`，其余仅去空白。"""
    value = (name or "").strip()
    if ecosystem == "pypi":
        value = re.sub(r"[-_.]+", "-", value.lower())
    return value


def dependency_id(repo_id: str, ecosystem: str, name: str, kind: str) -> str:
    raw = f"{repo_id}|{ecosystem}|{name}|{kind}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


def _clean_version(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _dep(
    ecosystem: str,
    name: str,
    version: object,
    kind: str,
    manifest: str,
) -> Optional[Dependency]:
    normalized = normalize_name(ecosystem, name)
    if not normalized or normalized.startswith("#"):
        return None
    return Dependency(
        ecosystem=ecosystem,
        name=normalized,
        version=_clean_version(version),
        kind="dev" if kind == "dev" else "runtime",
        manifest=manifest,
    )


# ---------------------------------------------------------------------------
# 清单解析（纯函数）
# ---------------------------------------------------------------------------


def parse_package_json(text: str, manifest: str = "package.json") -> list[Dependency]:
    """解析 package.json：dependencies / peerDependencies 为 runtime。"""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, dict):
        return []
    items: list[Dependency] = []
    sections = (
        ("dependencies", "runtime"),
        ("peerDependencies", "runtime"),
        ("optionalDependencies", "runtime"),
        ("devDependencies", "dev"),
    )
    for section, kind in sections:
        block = data.get(section)
        if not isinstance(block, dict):
            continue
        for name, version in block.items():
            dep = _dep("npm", str(name), version, kind, manifest)
            if dep:
                items.append(dep)
    return items


def parse_composer_json(text: str, manifest: str = "composer.json") -> list[Dependency]:
    """解析 composer.json：require 为 runtime，require-dev 为 dev。"""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, dict):
        return []
    items: list[Dependency] = []
    for section, kind in (("require", "runtime"), ("require-dev", "dev")):
        block = data.get(section)
        if not isinstance(block, dict):
            continue
        for name, version in block.items():
            dep = _dep("composer", str(name), version, kind, manifest)
            if dep:
                items.append(dep)
    return items


_REQUIREMENT_LINE = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*(?P<version>[<>=!~^ ].*)?$"
)


def parse_requirements_txt(text: str, manifest: str = "requirements.txt") -> list[Dependency]:
    """解析 requirements.txt：跳过注释 / 选项 / URL / 本地路径。"""
    items: list[Dependency] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(("-", "git+", "http://", "https://", ".", "/")):
            continue
        # 环境标记与 extras 只保留包名和版本约束
        line = line.split(";", 1)[0].strip()
        match = _REQUIREMENT_LINE.match(line)
        if not match:
            continue
        name = match.group("name")
        version = (match.group("version") or "").strip() or None
        dep = _dep("pypi", name, version, "runtime", manifest)
        if dep:
            items.append(dep)
    return items


def parse_pyproject_toml(text: str, manifest: str = "pyproject.toml") -> list[Dependency]:
    """解析 pyproject.toml：PEP 621 + Poetry 依赖表。"""
    try:
        import tomllib
    except ImportError:  # pragma: no cover - Python < 3.11
        return []
    try:
        data = tomllib.loads(text)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, dict):
        return []
    items: list[Dependency] = []

    project = data.get("project")
    if isinstance(project, dict):
        deps = project.get("dependencies")
        if isinstance(deps, list):
            for spec in deps:
                if isinstance(spec, str):
                    dep = _parse_pep508(spec, manifest)
                    if dep:
                        items.append(dep)
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            for group in optional.values():
                if isinstance(group, list):
                    for spec in group:
                        if isinstance(spec, str):
                            dep = _parse_pep508(spec, manifest, kind="dev")
                            if dep:
                                items.append(dep)

    tool = data.get("tool")
    poetry = tool.get("poetry") if isinstance(tool, dict) else None
    if isinstance(poetry, dict):
        blocks: list[tuple[object, str]] = [(poetry.get("dependencies"), "runtime")]
        legacy_dev = poetry.get("dev-dependencies")
        blocks.append((legacy_dev, "dev"))
        groups = poetry.get("group")
        if isinstance(groups, dict):
            for group in groups.values():
                if isinstance(group, dict):
                    blocks.append((group.get("dependencies"), "dev"))
        for block, kind in blocks:
            if not isinstance(block, dict):
                continue
            for name, version in block.items():
                if str(name).lower() == "python":
                    continue
                if isinstance(version, dict):
                    version = version.get("version")
                dep = _dep("pypi", str(name), version, kind, manifest)
                if dep:
                    items.append(dep)
    return items


def _parse_pep508(spec: str, manifest: str, kind: str = "runtime") -> Optional[Dependency]:
    """解析 `name[extra]>=1.0; python_version>'3.10'` 形式的依赖。"""
    line = spec.split(";", 1)[0].strip()
    match = _REQUIREMENT_LINE.match(line)
    if not match:
        return None
    return _dep(
        "pypi",
        match.group("name"),
        (match.group("version") or "").strip() or None,
        kind,
        manifest,
    )


def parse_go_mod(text: str, manifest: str = "go.mod") -> list[Dependency]:
    """解析 go.mod：require 单行与块；模块路径作为依赖名。"""
    items: list[Dependency] = []
    in_block = False
    for raw in text.splitlines():
        line = raw.split("//", 1)[0].strip()
        if not line:
            continue
        if line.startswith("require ("):
            in_block = True
            continue
        if in_block and line == ")":
            in_block = False
            continue
        if line.startswith("require "):
            line = line[len("require ") :].strip()
        elif not in_block:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        dep = _dep("go", parts[0], parts[1], "runtime", manifest)
        if dep:
            items.append(dep)
    return items


def parse_cargo_toml(text: str, manifest: str = "Cargo.toml") -> list[Dependency]:
    """解析 Cargo.toml：dependencies / dev-dependencies / build-dependencies。"""
    try:
        import tomllib
    except ImportError:  # pragma: no cover - Python < 3.11
        return []
    try:
        data = tomllib.loads(text)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, dict):
        return []
    items: list[Dependency] = []
    for section, kind in (
        ("dependencies", "runtime"),
        ("dev-dependencies", "dev"),
        ("build-dependencies", "runtime"),
    ):
        block = data.get(section)
        if not isinstance(block, dict):
            continue
        for name, value in block.items():
            if isinstance(value, dict):
                value = value.get("version")
            dep = _dep("cargo", str(name), value, kind, manifest)
            if dep:
                items.append(dep)
    return items


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_pom_xml(text: str, manifest: str = "pom.xml") -> list[Dependency]:
    """解析 pom.xml：groupId:artifactId，scope=test 记为 dev。"""
    try:
        root = ET.fromstring(text)
    except (ET.ParseError, ValueError, TypeError):
        return []
    items: list[Dependency] = []
    for node in root.iter():
        if _local_name(node.tag) != "dependency":
            continue
        values: dict[str, str] = {}
        for child in node:
            values[_local_name(child.tag)] = (child.text or "").strip()
        group = values.get("groupId", "")
        artifact = values.get("artifactId", "")
        if not group or not artifact:
            continue
        scope = values.get("scope", "")
        kind = "dev" if scope in ("test", "provided") else "runtime"
        dep = _dep("maven", f"{group}:{artifact}", values.get("version"), kind, manifest)
        if dep:
            items.append(dep)
    return items


_GEM_LINE = re.compile(
    r"""^\s*gem\s+['"](?P<name>[^'"]+)['"](?:\s*,\s*(?P<version>['"][^'"]+['"](?:\s*,\s*['"][^'"]+['"])*))?"""
)


def parse_gemfile(text: str, manifest: str = "Gemfile") -> list[Dependency]:
    """解析 Gemfile：group :development/:test 块内记为 dev。"""
    items: list[Dependency] = []
    group_stack: list[bool] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if re.match(r"^group\s+.*\bdo\s*$", line):
            group_stack.append(":development" in line or ":test" in line)
            continue
        if line == "end" and group_stack:
            group_stack.pop()
            continue
        match = _GEM_LINE.match(line)
        if not match:
            continue
        kind = "dev" if any(group_stack) else "runtime"
        if re.search(r"group:\s*\[?[^\]]*\b(development|test)\b", line):
            kind = "dev"
        version_text = match.group("version") or ""
        versions = re.findall(r"['\"]([^'\"]+)['\"]", version_text)
        dep = _dep("rubygems", match.group("name"), ",".join(versions) or None, kind, manifest)
        if dep:
            items.append(dep)
    return items


PARSERS: dict[str, Callable[[str, str], list[Dependency]]] = {
    "package.json": parse_package_json,
    "requirements.txt": parse_requirements_txt,
    "pyproject.toml": parse_pyproject_toml,
    "go.mod": parse_go_mod,
    "Cargo.toml": parse_cargo_toml,
    "pom.xml": parse_pom_xml,
    "Gemfile": parse_gemfile,
    "composer.json": parse_composer_json,
}


def parse_manifest(manifest: str, text: str) -> list[Dependency]:
    """按文件名解析清单；未知清单或解析异常返回空列表。"""
    parser = PARSERS.get(manifest)
    if parser is None:
        return []
    try:
        return parser(text, manifest)
    except Exception:  # noqa: BLE001 - 单份清单解析失败不影响整仓扫描
        logger.warning("解析清单失败: %s", manifest, exc_info=True)
        return []


# ---------------------------------------------------------------------------
# 扫描
# ---------------------------------------------------------------------------


def _github_raw_url(repo_id: str, manifest: str) -> str:
    return f"{RAW_BASE}/{repo_id}/HEAD/{manifest}"


def fetch_manifest(
    repo_id: str,
    manifest: str,
    *,
    token: str = "",
    timeout: float = 15.0,
    max_bytes: int = 512_000,
    client: Optional[httpx.Client] = None,
) -> Optional[str]:
    """拉取仓库根目录清单；404 返回 None，其他失败抛 `DependencyFetchError`。"""
    headers = {"User-Agent": "OpenFactory-VPS/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = _github_raw_url(repo_id, manifest)
    try:
        if client is not None:
            resp = client.get(url, headers=headers)
        else:
            with httpx.Client(timeout=timeout, follow_redirects=True) as http:
                resp = http.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise DependencyFetchError(f"{repo_id}/{manifest}: {exc}") from exc
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise DependencyFetchError(f"{repo_id}/{manifest}: HTTP {resp.status_code}")
    text = resp.text
    if len(text) > max_bytes:
        raise DependencyFetchError(f"{repo_id}/{manifest}: 清单超过 {max_bytes} 字节")
    return text


def _scan_candidates(
    db: Session,
    repo_ids: Optional[Iterable[str]],
    *,
    force: bool,
    limit: int,
) -> list[MyRepository]:
    stmt = select(MyRepository).order_by(MyRepository.stars.desc(), MyRepository.id.asc())
    ids = [item for item in (repo_ids or []) if item]
    if ids:
        stmt = stmt.where(MyRepository.id.in_(sorted(set(ids))))
    repos = list(db.scalars(stmt).all())

    if not force:
        ttl = max(0, int(get_settings().DEPENDENCY_SCAN_TTL_HOURS))
        cutoff = _utcnow() - timedelta(hours=ttl)
        fresh = {
            row.repo_id
            for row in db.scalars(
                select(RepoDependencyScan).where(
                    RepoDependencyScan.status.in_(("ok", "no_manifest"))
                )
            ).all()
            if row.scanned_at and row.scanned_at >= cutoff
        }
        repos = [repo for repo in repos if repo.id not in fresh]

    if limit > 0:
        repos = repos[:limit]
    return repos


def scan_repositories(
    db: Session,
    repo_ids: Optional[Iterable[str]] = None,
    *,
    force: bool = False,
    limit: int = 0,
    fetcher: Optional[Callable[[str, str], Optional[str]]] = None,
) -> dict:
    """扫描仓库依赖清单并覆盖式落库。

    `fetcher(repo_id, manifest)` 返回清单文本、None（不存在）或抛异常；
    默认使用 GitHub raw。单仓库失败只记录 `failed`，保留旧依赖数据。
    """
    settings = get_settings()
    if limit <= 0:
        limit = int(settings.DEPENDENCY_SCAN_MAX_REPOS)
    limit = max(1, min(limit, 500))
    fetch = fetcher or (
        lambda repo_id, manifest: fetch_manifest(
            repo_id,
            manifest,
            token=(settings.GITHUB_TOKEN or "").strip(),
            timeout=float(settings.DEPENDENCY_SCAN_TIMEOUT_SECONDS),
            max_bytes=int(settings.DEPENDENCY_MANIFEST_MAX_BYTES),
        )
    )

    repos = _scan_candidates(db, repo_ids, force=force, limit=limit)
    result = {
        "status": "ok",
        "scanned": 0,
        "ok": 0,
        "noManifest": 0,
        "failed": 0,
        "dependencies": 0,
        "repos": [],
    }

    for repo in repos:
        result["scanned"] += 1
        fetched: dict[str, str] = {}
        errors: list[str] = []
        for manifest, _ecosystem in MANIFESTS:
            try:
                text = fetch(repo.id, manifest)
            except Exception as exc:  # noqa: BLE001 - 单清单失败继续尝试其他清单
                errors.append(f"{manifest}: {str(exc)[:200]}")
                continue
            if text is not None:
                fetched[manifest] = text

        scan_row = db.get(RepoDependencyScan, repo.id)
        if scan_row is None:
            scan_row = RepoDependencyScan(repo_id=repo.id)
            db.add(scan_row)

        if not fetched:
            if errors:
                # 全部清单拉取失败：保留旧依赖，仅更新扫描状态
                existing = db.scalar(
                    select(func.count()).select_from(RepoDependency).where(
                        RepoDependency.repo_id == repo.id
                    )
                )
                scan_row.status = "failed"
                scan_row.error = "; ".join(errors)[:1000]
                scan_row.dependency_count = int(existing or 0)
                scan_row.scanned_at = _utcnow()
                result["failed"] += 1
                result["repos"].append(
                    {"repoId": repo.id, "status": "failed", "error": scan_row.error}
                )
            else:
                db.execute(delete(RepoDependency).where(RepoDependency.repo_id == repo.id))
                scan_row.status = "no_manifest"
                scan_row.manifests = None
                scan_row.error = None
                scan_row.dependency_count = 0
                scan_row.scanned_at = _utcnow()
                result["noManifest"] += 1
                result["repos"].append({"repoId": repo.id, "status": "no_manifest"})
            continue

        # 覆盖式写入：先清空该仓库旧依赖，再插入本次解析结果
        db.execute(delete(RepoDependency).where(RepoDependency.repo_id == repo.id))
        seen: set[str] = set()
        count = 0
        for manifest, text in fetched.items():
            for dep in parse_manifest(manifest, text):
                key = dependency_id(repo.id, dep.ecosystem, dep.name, dep.kind)
                if key in seen:
                    continue
                seen.add(key)
                db.add(
                    RepoDependency(
                        id=key,
                        repo_id=repo.id,
                        ecosystem=dep.ecosystem,
                        name=dep.name,
                        version=dep.version,
                        kind=dep.kind,
                        manifest=dep.manifest,
                    )
                )
                count += 1

        scan_row.status = "ok"
        scan_row.manifests = ",".join(fetched.keys())
        scan_row.error = "; ".join(errors)[:1000] if errors else None
        scan_row.dependency_count = count
        scan_row.scanned_at = _utcnow()
        result["ok"] += 1
        result["dependencies"] += count
        result["repos"].append(
            {
                "repoId": repo.id,
                "status": "ok",
                "manifests": list(fetched.keys()),
                "dependencyCount": count,
            }
        )

    db.commit()
    return result


# ---------------------------------------------------------------------------
# 聚合
# ---------------------------------------------------------------------------


def _normalize_repo_ids(repo_ids: Optional[Iterable[str]]) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for item in repo_ids or []:
        value = (item or "").strip()
        if value and value not in seen:
            seen.add(value)
            values.append(value)
    return values


def _round(value: float) -> float:
    return round(float(value), 4)


def aggregate_dependencies(
    db: Session,
    repo_ids: Optional[Iterable[str]] = None,
    *,
    top: int = 20,
) -> dict:
    """聚合当前（或指定）仓库的依赖分析结果；只读本地表，不访问网络。"""
    top = max(1, min(int(top), 100))
    ids = _normalize_repo_ids(repo_ids)
    stmt = select(MyRepository).order_by(MyRepository.stars.desc(), MyRepository.id.asc())
    if ids:
        stmt = stmt.where(MyRepository.id.in_(ids))
    repos = list(db.scalars(stmt).all())
    repo_map = {repo.id: repo for repo in repos}
    repo_keys = list(repo_map.keys())

    deps: list[RepoDependency] = []
    scans: dict[str, RepoDependencyScan] = {}
    if repo_keys:
        deps = list(
            db.scalars(select(RepoDependency).where(RepoDependency.repo_id.in_(repo_keys))).all()
        )
        scans = {
            row.repo_id: row
            for row in db.scalars(
                select(RepoDependencyScan).where(RepoDependencyScan.repo_id.in_(repo_keys))
            ).all()
        }

    language_counts: dict[str, int] = {}
    for repo in repos:
        language = (repo.language or "").strip()
        if language:
            language_counts[language] = language_counts.get(language, 0) + 1
    language_total = sum(language_counts.values())
    tech_stack = [
        {
            "language": language,
            "count": count,
            "percent": _round(count / language_total) if language_total else 0.0,
        }
        for language, count in sorted(language_counts.items(), key=lambda item: (-item[1], item[0]))
    ]

    deps_by_repo: dict[str, list[RepoDependency]] = {}
    for dep in deps:
        deps_by_repo.setdefault(dep.repo_id, []).append(dep)

    analyzed = sum(1 for repo in repos if scans.get(repo.id) and scans[repo.id].status == "ok")
    no_manifest = sum(
        1 for repo in repos if scans.get(repo.id) and scans[repo.id].status == "no_manifest"
    )
    failed = sum(1 for repo in repos if scans.get(repo.id) and scans[repo.id].status == "failed")
    pending = len(repos) - analyzed - no_manifest - failed

    ecosystems: dict[str, dict[str, set[str] | int]] = {
        eco: {"repos": set(), "rows": 0} for eco in ECOSYSTEMS
    }
    for dep in deps:
        block = ecosystems.setdefault(dep.ecosystem, {"repos": set(), "rows": 0})
        block["repos"].add(dep.repo_id)  # type: ignore[union-attr]
        block["rows"] = int(block["rows"]) + 1
    ecosystem_out = [
        {
            "ecosystem": eco,
            "repos": len(block["repos"]),  # type: ignore[arg-type]
            "dependencies": int(block["rows"]),
        }
        for eco, block in ecosystems.items()
        if block["repos"] or block["rows"]
    ]
    ecosystem_out.sort(key=lambda item: (-item["repos"], -item["dependencies"], item["ecosystem"]))

    grouped: dict[tuple[str, str], dict] = {}
    for dep in deps:
        key = (dep.ecosystem, dep.name)
        item = grouped.setdefault(
            key,
            {
                "name": dep.name,
                "ecosystem": dep.ecosystem,
                "kinds": set(),
                "versions": [],
                "repos": set(),
                "languages": {},
            },
        )
        item["kinds"].add(dep.kind)
        if dep.version and dep.version not in item["versions"] and len(item["versions"]) < 3:
            item["versions"].append(dep.version)
        item["repos"].add(dep.repo_id)
        language = (repo_map[dep.repo_id].language or "").strip() or "未知"
        item["languages"][language] = item["languages"].get(language, 0) + 1

    # 覆盖率分母：已分析仓库数；失败仓库保留的旧依赖也计入，避免覆盖率超过 100%
    base = max(analyzed, len({dep.repo_id for dep in deps}))
    dependency_out: list[dict] = []
    links: list[dict] = []
    for (ecosystem, name), item in grouped.items():
        repo_count = len(item["repos"])
        languages = [
            {"language": language, "count": count}
            for language, count in sorted(
                item["languages"].items(), key=lambda pair: (-pair[1], pair[0])
            )
        ]
        dependency_out.append(
            {
                "name": name,
                "ecosystem": ecosystem,
                "kind": "dev" if item["kinds"] == {"dev"} else "runtime",
                "repoCount": repo_count,
                "coverage": _round(repo_count / base) if base else 0.0,
                "versions": item["versions"],
                "languages": languages,
                "repos": [
                    {
                        "id": repo_id,
                        "name": repo_map[repo_id].name,
                        "language": repo_map[repo_id].language or "",
                    }
                    for repo_id in sorted(item["repos"])
                ][:5],
            }
        )
        if repo_count >= 1:
            for language in languages:
                links.append(
                    {
                        "dependency": name,
                        "ecosystem": ecosystem,
                        "language": language["language"],
                        "count": language["count"],
                        "strength": _round(language["count"] / repo_count),
                    }
                )

    dependency_out.sort(key=lambda item: (-item["repoCount"], item["name"]))
    top_dependencies = dependency_out[:top]
    top_keys = {(item["ecosystem"], item["name"]) for item in top_dependencies}
    links = [
        link
        for link in links
        if (link["ecosystem"], link["dependency"]) in top_keys
    ]
    links.sort(key=lambda item: (-item["count"], -item["strength"], item["dependency"]))

    repo_out: list[dict] = []
    for repo in repos:
        scan = scans.get(repo.id)
        repo_deps = deps_by_repo.get(repo.id, [])
        repo_out.append(
            {
                "repoId": repo.id,
                "name": repo.name,
                "language": repo.language or "",
                "status": scan.status if scan else "pending",
                "manifests": (scan.manifests or "").split(",") if scan and scan.manifests else [],
                "dependencyCount": len(repo_deps),
                "error": scan.error if scan else None,
                "topDependencies": [
                    {"name": dep.name, "ecosystem": dep.ecosystem}
                    for dep in sorted(repo_deps, key=lambda row: (row.ecosystem, row.name))[:5]
                ],
            }
        )
    repo_out.sort(key=lambda item: (-item["dependencyCount"], item["repoId"]))

    return {
        "generatedAt": _utcnow().isoformat(timespec="seconds") + "Z",
        "summary": {
            "repos": len(repos),
            "analyzed": analyzed,
            "noManifest": no_manifest,
            "failed": failed,
            "pending": pending,
            "dependencyRows": len(deps),
            "uniqueDependencies": len(grouped),
            "ecosystems": len(ecosystem_out),
        },
        "techStack": tech_stack,
        "ecosystems": ecosystem_out,
        "dependencies": top_dependencies,
        "links": links,
        "repos": repo_out,
    }
