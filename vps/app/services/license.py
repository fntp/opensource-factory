"""License 识别与合规提示（M6-06）。

职责：
- 维护常用开源许可证目录（SPDX / 名称 / 分类 / 风险 / 义务 / 警告）；
- 把 GitHub API `license` 对象、SPDX 标识或名称归一化为目录条目；
- 在缺少仓库元数据时，从 README 的 SPDX 标识、徽章或许可证段落做启发式识别；
- 输出前端可直接展示的合规提示结构。

设计约束：纯函数、无网络、无数据库依赖，便于 VPS 任务与测试复用。
合规提示仅为工程辅助信息，不构成法律意见。
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Optional
from urllib.parse import unquote

CATEGORY_LABELS: dict[str, str] = {
    "permissive": "宽松许可",
    "weak-copyleft": "弱著佐权",
    "strong-copyleft": "强著佐权",
    "network-copyleft": "网络著佐权",
    "public-domain": "公共领域",
    "unknown": "未知许可",
}

CATEGORY_DESCRIPTIONS: dict[str, str] = {
    "permissive": "允许商用、修改、再分发与闭源衍生，通常只需保留版权与许可证声明。",
    "weak-copyleft": "允许与闭源代码组合，但修改过的库文件本身需要以同许可证开源。",
    "strong-copyleft": "分发衍生作品时，衍生作品整体需要以同许可证开源。",
    "network-copyleft": "通过网络提供服务也可能被视为分发，需要向用户提供源码。",
    "public-domain": "作者放弃版权或贡献到公共领域，几乎没有强制义务。",
    "unknown": "未识别到有效许可证，默认保留所有权利，使用前需要获得作者授权。",
}

RISK_LABELS: dict[str, str] = {
    "low": "低风险",
    "medium": "中风险",
    "high": "高风险",
    "unknown": "未知风险",
}


@dataclass(frozen=True)
class LicenseDefinition:
    """单个许可证的合规口径。"""

    spdx: str
    name: str
    category: str
    risk: str
    summary: str
    obligations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


LICENSE_CATALOG: tuple[LicenseDefinition, ...] = (
    LicenseDefinition(
        "MIT",
        "MIT License",
        "permissive",
        "low",
        "允许商用、修改、再分发与闭源衍生，需保留版权与许可证声明。",
        ("保留版权声明", "保留许可证文本"),
    ),
    LicenseDefinition(
        "Apache-2.0",
        "Apache License 2.0",
        "permissive",
        "low",
        "允许商用、修改、再分发与专利授权，需保留许可证与 NOTICE 文件并标注修改。",
        ("保留许可证文本", "保留 NOTICE 文件", "标注修改过的文件"),
    ),
    LicenseDefinition(
        "BSD-2-Clause",
        "BSD 2-Clause License",
        "permissive",
        "low",
        "允许商用、修改与再分发，需保留版权声明与免责声明。",
        ("保留版权声明", "保留免责声明"),
    ),
    LicenseDefinition(
        "BSD-3-Clause",
        "BSD 3-Clause License",
        "permissive",
        "low",
        "允许商用、修改与再分发，需保留版权声明，且不得用作者名义为衍生品背书。",
        ("保留版权声明", "不得使用作者名义背书"),
    ),
    LicenseDefinition(
        "ISC",
        "ISC License",
        "permissive",
        "low",
        "与 MIT 等价的宽松许可，需保留版权与许可证声明。",
        ("保留版权声明", "保留许可证文本"),
    ),
    LicenseDefinition(
        "Zlib",
        "zlib License",
        "permissive",
        "low",
        "允许商用与修改，需保留来源声明，且不得歪曲软件来源。",
        ("保留来源声明", "不得歪曲来源"),
    ),
    LicenseDefinition(
        "0BSD",
        "BSD Zero Clause License",
        "public-domain",
        "low",
        "近乎公共领域，允许任意使用，无需保留版权声明。",
        (),
    ),
    LicenseDefinition(
        "MPL-2.0",
        "Mozilla Public License 2.0",
        "weak-copyleft",
        "medium",
        "文件级著佐权：修改过的 MPL 文件需以 MPL 开源，其他文件可闭源。",
        ("修改的 MPL 文件需开源", "保留许可证与源码获取方式"),
        ("与 GPL 组合时需确认兼容性",),
    ),
    LicenseDefinition(
        "LGPL-2.1",
        "GNU Lesser General Public License 2.1",
        "weak-copyleft",
        "medium",
        "允许动态链接闭源程序，但修改库本身需以 LGPL 开源。",
        ("修改的库需开源", "允许用户替换库版本"),
    ),
    LicenseDefinition(
        "LGPL-3.0",
        "GNU Lesser General Public License 3.0",
        "weak-copyleft",
        "medium",
        "允许动态链接闭源程序，但修改库本身需以 LGPL 开源，并保留安装信息。",
        ("修改的库需开源", "提供安装信息以便替换库"),
    ),
    LicenseDefinition(
        "EPL-2.0",
        "Eclipse Public License 2.0",
        "weak-copyleft",
        "medium",
        "修改过的 EPL 文件需以 EPL 开源，其他代码可闭源；含专利授权。",
        ("修改的 EPL 文件需开源", "保留许可证与专利条款"),
    ),
    LicenseDefinition(
        "GPL-2.0",
        "GNU General Public License 2.0",
        "strong-copyleft",
        "high",
        "分发衍生作品时，衍生作品整体需以 GPL-2.0 开源并提供源码。",
        ("衍生作品需以 GPL 开源", "分发时提供完整源码"),
        ("闭源商用分发通常不可行",),
    ),
    LicenseDefinition(
        "GPL-3.0",
        "GNU General Public License 3.0",
        "strong-copyleft",
        "high",
        "分发衍生作品时，衍生作品整体需以 GPL-3.0 开源，并禁止额外限制。",
        ("衍生作品需以 GPL 开源", "分发时提供完整源码", "不得附加额外限制"),
        ("闭源商用分发通常不可行", "含专利授权与反 Tivoization 条款"),
    ),
    LicenseDefinition(
        "AGPL-3.0",
        "GNU Affero General Public License 3.0",
        "network-copyleft",
        "high",
        "通过网络向用户提供服务也可能触发源码开放义务，影响 SaaS 场景。",
        ("网络服务需提供完整源码", "衍生作品需以 AGPL 开源"),
        ("SaaS / 托管服务需重点评估", "闭源商用通常不可行"),
    ),
    LicenseDefinition(
        "Unlicense",
        "The Unlicense",
        "public-domain",
        "low",
        "贡献到公共领域，允许任意使用，无强制义务。",
        (),
        ("建议保留出处与免责声明",),
    ),
    LicenseDefinition(
        "CC0-1.0",
        "Creative Commons Zero 1.0",
        "public-domain",
        "low",
        "放弃版权与相关权利，允许任意使用，无强制义务。",
        (),
        ("建议保留出处",),
    ),
)

CATALOG_BY_SPDX: dict[str, LicenseDefinition] = {item.spdx: item for item in LICENSE_CATALOG}

# 归一化别名（键为仅保留字母数字的小写形式）
_ALIASES: dict[str, str] = {}


def _alias_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _register_aliases(spdx: str, *aliases: str) -> None:
    _ALIASES[_alias_key(spdx)] = spdx
    for alias in aliases:
        _ALIASES[_alias_key(alias)] = spdx


_register_aliases("MIT", "MIT License", "The MIT License", "Expat")
_register_aliases("Apache-2.0", "Apache 2.0", "Apache License 2.0", "Apache License, Version 2.0", "Apache-2")
_register_aliases("BSD-2-Clause", "BSD 2-Clause", "BSD 2-Clause License", "Simplified BSD", "FreeBSD")
_register_aliases("BSD-3-Clause", "BSD 3-Clause", "BSD 3-Clause License", "New BSD", "Modified BSD")
_register_aliases("ISC", "ISC License")
_register_aliases("Zlib", "zlib License", "zlib/libpng")
_register_aliases("0BSD", "BSD Zero Clause License", "Zero-Clause BSD")
_register_aliases("MPL-2.0", "MPL 2.0", "Mozilla Public License 2.0", "Mozilla Public License, Version 2.0")
_register_aliases("LGPL-2.1", "LGPL 2.1", "LGPLv2.1", "GNU Lesser General Public License 2.1")
_register_aliases("LGPL-3.0", "LGPL 3.0", "LGPLv3", "GNU Lesser General Public License 3.0")
_register_aliases("EPL-2.0", "EPL 2.0", "Eclipse Public License 2.0", "Eclipse Public License, Version 2.0")
_register_aliases("GPL-2.0", "GPL 2.0", "GPLv2", "GNU General Public License 2.0", "GNU General Public License, Version 2")
_register_aliases("GPL-3.0", "GPL 3.0", "GPLv3", "GNU General Public License 3.0", "GNU General Public License, Version 3")
_register_aliases("AGPL-3.0", "AGPL 3.0", "AGPLv3", "GNU Affero General Public License 3.0", "GNU Affero General Public License, Version 3")
_register_aliases("Unlicense", "The Unlicense")
_register_aliases("CC0-1.0", "CC0 1.0", "CC0", "Creative Commons Zero 1.0")

# README 启发式：顺序重要（AGPL / LGPL 必须先于 GPL）
_README_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?<![A-Za-z])AGPL[-\s]?(?:v|version)?\s*3(?:\.0)?\b", re.I), "AGPL-3.0"),
    (re.compile(r"GNU\s+Affero\s+General\s+Public\s+License", re.I), "AGPL-3.0"),
    (re.compile(r"(?<![A-Za-z])LGPL[-\s]?(?:v|version)?\s*3(?:\.0)?\b", re.I), "LGPL-3.0"),
    (re.compile(r"(?<![A-Za-z])LGPL(?:[-\s]?(?:v|version)?\s*2\.1)\b", re.I), "LGPL-2.1"),
    (re.compile(r"GNU\s+Lesser\s+General\s+Public\s+License[^\n]{0,40}2\.1", re.I), "LGPL-2.1"),
    (re.compile(r"GNU\s+Lesser\s+General\s+Public\s+License[^\n]{0,40}3", re.I), "LGPL-3.0"),
    (re.compile(r"(?<![A-Za-z])GPL[-\s]?(?:v|version)?\s*3(?:\.0)?\b", re.I), "GPL-3.0"),
    (re.compile(r"(?<![A-Za-z])GPL[-\s]?(?:v|version)?\s*2(?:\.0)?\b", re.I), "GPL-2.0"),
    (re.compile(r"GNU\s+General\s+Public\s+License[^\n]{0,40}3", re.I), "GPL-3.0"),
    (re.compile(r"GNU\s+General\s+Public\s+License[^\n]{0,40}2", re.I), "GPL-2.0"),
    (re.compile(r"Apache(?:\s+License)?[,\s-]*(?:Version\s*)?2(?:\.0)?\b", re.I), "Apache-2.0"),
    (re.compile(r"Mozilla\s+Public\s+License[,\s]*(?:Version\s*)?2\.0", re.I), "MPL-2.0"),
    (re.compile(r"(?<![A-Za-z])MPL[-\s]?2\.0\b", re.I), "MPL-2.0"),
    (re.compile(r"Eclipse\s+Public\s+License[,\s]*(?:Version\s*)?2\.0", re.I), "EPL-2.0"),
    (re.compile(r"(?<![A-Za-z])EPL[-\s]?2\.0\b", re.I), "EPL-2.0"),
    (re.compile(r"\bMIT\s+License\b", re.I), "MIT"),
    (re.compile(r"\bThe\s+MIT\s+License\b", re.I), "MIT"),
    (re.compile(r"\bBSD[-\s]?3[-\s]?Clause\b", re.I), "BSD-3-Clause"),
    (re.compile(r"\bNew\s+BSD\b", re.I), "BSD-3-Clause"),
    (re.compile(r"\bBSD[-\s]?2[-\s]?Clause\b", re.I), "BSD-2-Clause"),
    (re.compile(r"\bSimplified\s+BSD\b", re.I), "BSD-2-Clause"),
    (re.compile(r"\bISC\s+License\b", re.I), "ISC"),
    (re.compile(r"\bThe\s+Unlicense\b", re.I), "Unlicense"),
    (re.compile(r"\bCC0[-\s]?1\.0\b", re.I), "CC0-1.0"),
    (re.compile(r"\bCreative\s+Commons\s+Zero\b", re.I), "CC0-1.0"),
    (re.compile(r"\bzlib\s+License\b", re.I), "Zlib"),
    (re.compile(r"\b0BSD\b", re.I), "0BSD"),
)

_SPDX_LINE_RE = re.compile(
    r"SPDX-License-Identifier\s*:\s*([A-Za-z0-9.+\-]+(?:\s+(?:OR|AND)\s+[A-Za-z0-9.+\-]+)*)",
    re.I,
)
_BADGE_RE = re.compile(
    r"(?:img\.shields\.io/badge|badge)/license-([^)\s\"'<>]+?)"
    r"-(?:brightgreen|green|yellowgreen|yellow|orange|red|blue|lightgrey|informational|success|critical)",
    re.I,
)


def normalize_spdx(value: Any) -> Optional[str]:
    """把 SPDX 标识 / 名称 / GitHub license key 归一化为目录中的 SPDX。"""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if raw.upper() in {"NOASSERTION", "NONE", "UNKNOWN", "OTHER"}:
        return None
    direct = CATALOG_BY_SPDX.get(raw)
    if direct:
        return direct.spdx
    # SPDX 版本后缀：`-only` / `-or-later` / `+` 统一归到基础版本
    stripped = re.sub(r"-(?:only|or-later)$", "", raw, flags=re.I)
    if stripped.endswith("+"):
        stripped = stripped[:-1]
    direct = CATALOG_BY_SPDX.get(stripped)
    if direct:
        return direct.spdx
    key = _alias_key(raw)
    if key in _ALIASES:
        return _ALIASES[key]
    # 去掉常见前后缀后再试一次：如 "The MIT License (MIT)"
    cleaned = re.sub(r"\([^)]*\)", " ", raw)
    key = _alias_key(cleaned)
    return _ALIASES.get(key)


def identify_github_license(value: Any) -> Optional[dict[str, str]]:
    """解析 GitHub API `license` 对象；无法识别时返回 None。"""
    if isinstance(value, dict):
        name = str(value.get("name") or "").strip()
        spdx = value.get("spdx_id") or value.get("key") or name
        normalized = normalize_spdx(spdx) or normalize_spdx(name)
        if normalized:
            return {"spdxId": normalized, "name": name or CATALOG_BY_SPDX[normalized].name}
        if name:
            return {"spdxId": "", "name": name}
        return None
    if isinstance(value, str):
        normalized = normalize_spdx(value)
        if normalized:
            return {"spdxId": normalized, "name": CATALOG_BY_SPDX[normalized].name}
        if value.strip():
            return {"spdxId": "", "name": value.strip()}
    return None


def _badge_token_to_spdx(token: str) -> Optional[str]:
    cleaned = unquote(token).replace("_", " ").replace("--", "-")
    cleaned = re.sub(r"[-\s]+", " ", cleaned).strip()
    return normalize_spdx(cleaned) or normalize_spdx(token)


def detect_license_from_readme(md: str, *, max_chars: int = 30000) -> Optional[dict[str, str]]:
    """从 README 文本识别许可证；识别不到返回 None。

    顺序：SPDX-License-Identifier → shields 徽章 → 许可证名称正则。
    """
    if not md:
        return None
    text = html.unescape(str(md)[: max(0, max_chars)])
    text = unquote(text).replace(" ", " ")

    spdx_line = _SPDX_LINE_RE.search(text)
    if spdx_line:
        first = re.split(r"\s+(?:OR|AND)\s+", spdx_line.group(1), maxsplit=1, flags=re.I)[0]
        normalized = normalize_spdx(first)
        if normalized:
            return {"spdxId": normalized, "name": CATALOG_BY_SPDX[normalized].name}

    for match in _BADGE_RE.finditer(text):
        normalized = _badge_token_to_spdx(match.group(1))
        if normalized:
            return {"spdxId": normalized, "name": CATALOG_BY_SPDX[normalized].name}

    for pattern, spdx in _README_PATTERNS:
        if pattern.search(text):
            return {"spdxId": spdx, "name": CATALOG_BY_SPDX[spdx].name}
    return None


def _isoformat(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def build_compliance_hint(
    spdx_id: Any = None,
    name: Any = None,
    *,
    source: Optional[str] = None,
    checked_at: Any = None,
) -> dict[str, Any]:
    """构造前端展示用的 License 合规提示。"""
    normalized = normalize_spdx(spdx_id) or normalize_spdx(name)
    if normalized:
        definition = CATALOG_BY_SPDX[normalized]
        return {
            "spdxId": definition.spdx,
            "name": definition.name,
            "category": definition.category,
            "categoryLabel": CATEGORY_LABELS[definition.category],
            "riskLevel": definition.risk,
            "riskLabel": RISK_LABELS[definition.risk],
            "summary": definition.summary,
            "obligations": list(definition.obligations),
            "warnings": list(definition.warnings),
            "source": source,
            "checkedAt": _isoformat(checked_at),
        }

    display_name = str(name).strip() if name else None
    return {
        "spdxId": None,
        "name": display_name,
        "category": "unknown",
        "categoryLabel": CATEGORY_LABELS["unknown"],
        "riskLevel": "unknown",
        "riskLabel": RISK_LABELS["unknown"],
        "summary": "未识别到有效许可证，默认保留所有权利；复制、修改、分发或商用前需联系作者获取明确授权。",
        "obligations": ["使用前联系作者获取授权", "保留原始出处与作者信息"],
        "warnings": ["无许可证不等于可以自由使用", "商用 / SaaS 场景建议进行法务复核"],
        "source": source,
        "checkedAt": _isoformat(checked_at),
    }


def catalog_payload() -> dict[str, Any]:
    """返回许可证目录与分类说明（供前端 / API 使用）。"""
    return {
        "categories": [
            {
                "key": key,
                "label": CATEGORY_LABELS[key],
                "description": CATEGORY_DESCRIPTIONS[key],
            }
            for key in CATEGORY_LABELS
        ],
        "licenses": [
            {
                "spdxId": item.spdx,
                "name": item.name,
                "category": item.category,
                "categoryLabel": CATEGORY_LABELS[item.category],
                "riskLevel": item.risk,
                "riskLabel": RISK_LABELS[item.risk],
                "summary": item.summary,
                "obligations": list(item.obligations),
                "warnings": list(item.warnings),
            }
            for item in LICENSE_CATALOG
        ],
    }


def summarize_license_rows(rows: Iterable[tuple[Optional[str], Optional[str]]]) -> dict[str, Any]:
    """按 (spdx, name) 行统计许可证分布与风险分布。"""
    counts: dict[str, dict[str, Any]] = {}
    risk_counts = {key: 0 for key in RISK_LABELS}
    total = 0
    for spdx_id, name in rows:
        total += 1
        hint = build_compliance_hint(spdx_id, name)
        key = hint["spdxId"] or "__unknown__"
        entry = counts.setdefault(
            key,
            {
                "spdxId": hint["spdxId"],
                "name": hint["name"] or "未识别",
                "count": 0,
                "category": hint["category"],
                "categoryLabel": hint["categoryLabel"],
                "riskLevel": hint["riskLevel"],
            },
        )
        entry["count"] += 1
        risk_counts[hint["riskLevel"]] = risk_counts.get(hint["riskLevel"], 0) + 1
    licenses = sorted(counts.values(), key=lambda item: (-item["count"], str(item["name"])))
    return {
        "total": total,
        "known": sum(item["count"] for item in licenses if item["spdxId"]),
        "unknown": sum(item["count"] for item in licenses if not item["spdxId"]),
        "riskCounts": risk_counts,
        "licenses": licenses,
    }
