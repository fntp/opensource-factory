#!/usr/bin/env python3
"""M8 验收 · 多端接入跨分支走查（零额外依赖、可离线复跑）。

覆盖已交付的 M8-01~04，并对平台仍为 pending 的 M8-05/06/07 输出缺口状态：

    M8-01 PWA 与移动端适配（manifest / Service Worker / 离线页 / 安装引导 / 移动端导航）
    M8-02 浏览器扩展（MV3 manifest / 扩展源码 / edge 令牌接口 / 迁移 / admin 令牌页）
    M8-03 Telegram Bot（命令纯函数 / webhook 路由 / 绑定码 / 迁移 / admin 面板）
    M8-04 快捷入口评估（6 平台排名 / 16 项 API 就绪度 / 报告与契约）
    M8-05~07 缺口检查（开放 API / CLI / 离线本地数据）

用法（在 vps/ 下）：

    python scripts/m8_acceptance.py
    python scripts/m8_acceptance.py --strict
    python scripts/m8_acceptance.py --report-md docs/planning/acceptance-m8-report.md \
        --report-json docs/planning/acceptance-m8-report.json
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

VPS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = VPS_ROOT.parent
sys.path.insert(0, str(VPS_ROOT))

RESULTS: list[dict[str, object]] = []


# ---------------------------------------------------------------------------
# 结果记录
# ---------------------------------------------------------------------------
def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def assert_equal(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}：期望 {expected!r}，实际 {actual!r}")


def check(cid: str, title: str, fn, *args) -> None:
    started = time.perf_counter()
    try:
        detail = fn(*args) or ""
        RESULTS.append(
            {
                "id": cid,
                "title": title,
                "status": "PASS",
                "detail": str(detail),
                "durationMs": round((time.perf_counter() - started) * 1000, 1),
            }
        )
        print(f"  ✔ [PASS] {title}" + (f" — {detail}" if detail else ""))
    except Exception as exc:  # noqa: BLE001 - 单项失败不影响其余检查
        RESULTS.append(
            {
                "id": cid,
                "title": title,
                "status": "FAIL",
                "detail": str(exc),
                "durationMs": round((time.perf_counter() - started) * 1000, 1),
            }
        )
        print(f"  ✖ [FAIL] {title} — {exc}")


def gap(cid: str, title: str, detail: str) -> None:
    RESULTS.append(
        {"id": cid, "title": title, "status": "GAP", "detail": detail, "durationMs": 0.0}
    )
    print(f"  ○ [GAP ] {title} — {detail}")


# ---------------------------------------------------------------------------
# 读取辅助
# ---------------------------------------------------------------------------
def _read(relative: str) -> str:
    path = REPO_ROOT / relative
    assert_true(path.exists(), f"缺少文件：{relative}")
    return path.read_text(encoding="utf-8")


def _json(relative: str) -> dict:
    return json.loads(_read(relative))


def _exists(relative: str) -> bool:
    return (REPO_ROOT / relative).exists()


# ---------------------------------------------------------------------------
# M8-01 PWA 与移动端
# ---------------------------------------------------------------------------
def check_pwa_manifest() -> str:
    manifest = _json("admin/public/manifest.webmanifest")
    assert_equal(manifest.get("name"), "开源项目工厂", "manifest name")
    assert_equal(manifest.get("short_name"), "开源项目工厂", "manifest short_name")
    assert_equal(manifest.get("start_url"), "/", "manifest start_url")
    assert_equal(manifest.get("display"), "standalone", "manifest display")
    assert_true(bool(manifest.get("theme_color")), "缺少 theme_color")
    assert_true(bool(manifest.get("background_color")), "缺少 background_color")
    icons = manifest.get("icons") or []
    sizes = {item.get("sizes") for item in icons}
    purposes = {item.get("purpose", "any") for item in icons}
    for expected in ("192x192", "512x512"):
        assert_true(expected in sizes, f"缺少图标尺寸 {expected}：{sizes}")
    assert_true("maskable" in purposes, f"缺少 maskable 图标：{purposes}")
    for icon in icons:
        src = str(icon.get("src") or "").lstrip("/")
        assert_true(_exists(f"admin/public/{src}"), f"图标文件不存在：{src}")
    shortcuts = manifest.get("shortcuts") or []
    assert_true(len(shortcuts) >= 3, f"快捷入口不足：{len(shortcuts)}")
    return f"icons={sorted(sizes)} shortcuts={len(shortcuts)}"


def check_pwa_service_worker() -> str:
    sw = _read("admin/public/sw.js")
    for needle in ("CACHE_VERSION", "APP_SHELL", "/offline.html", "addAll", "fetch"):
        assert_true(needle in sw, f"sw.js 缺少 {needle}")
    assert_true("pathname.startsWith('/api/')" in sw, "sw.js 未排除 /api/*")
    assert_true("method !== 'GET'" in sw or "method !== \"GET\"" in sw, "sw.js 未排除非 GET")
    offline = _read("admin/public/offline.html")
    assert_true("离线" in offline, "offline.html 内容异常")
    index = _read("admin/index.html")
    assert_true('rel="manifest"' in index, "index.html 未引用 manifest")
    assert_true("apple-touch-icon" in index, "index.html 缺少 apple-touch-icon")
    return "App Shell 预缓存 / 离线兜底 / /api 排除 / manifest 引用"


def check_pwa_integration() -> str:
    pwa = _read("admin/src/lib/pwa.ts")
    for fn in ("isStandaloneApp", "isIosDevice", "shouldShowInstallPrompt", "markInstallDismissed"):
        assert_true(f"function {fn}" in pwa, f"pwa.ts 缺少 {fn}")
    layout = _read("admin/src/components/layout/authenticated-layout.tsx")
    assert_true("PwaProvider" in layout, "布局未接入 PwaProvider")
    assert_true("MobileTabBar" in layout, "布局未接入 MobileTabBar")
    tab = _read("admin/src/components/layout/mobile-tab-bar.tsx")
    assert_true("md:hidden" in tab, "移动端导航缺少断点隐藏")
    assert_true("safe-area-inset-bottom" in tab, "移动端导航缺少安全区适配")
    main = _read("admin/src/main.tsx")
    assert_true("registerServiceWorker" in main, "main.tsx 未注册 Service Worker")
    return "安装引导 / 离线横幅 / 底部导航 / 安全区 / SW 注册"


# ---------------------------------------------------------------------------
# M8-02 浏览器扩展
# ---------------------------------------------------------------------------
def check_extension_manifest() -> str:
    manifest = _json("extension/manifest.json")
    assert_equal(manifest.get("manifest_version"), 3, "manifest_version")
    permissions = set(manifest.get("permissions") or [])
    for expected in ("activeTab", "scripting", "storage"):
        assert_true(expected in permissions, f"缺少权限 {expected}：{permissions}")
    background = manifest.get("background") or {}
    assert_true(bool(background.get("service_worker")), "缺少 background.service_worker")
    assert_true(bool((manifest.get("action") or {}).get("default_popup")), "缺少 action popup")
    assert_true(bool(manifest.get("options_page")), "缺少 options_page")
    for icon in (manifest.get("action") or {}).get("default_icon", {}).values():
        assert_true(_exists(f"extension/{icon}"), f"扩展图标不存在：{icon}")
    for path in ("extension/src/background.js", "extension/src/popup.js", "extension/src/options.js"):
        _read(path)
    return f"MV3 permissions={sorted(permissions)}"


def check_extension_core() -> str:
    repo = _read("extension/src/lib/repo.js")
    for fn in ("parseRepoFullName", "parseRepoUrl", "buildBookmarkPayload", "normalizeApiBase"):
        assert_true(f"function {fn}" in repo, f"repo.js 缺少 {fn}")
    _read("extension/src/content/extract.js")
    tests = _read("extension/tests/repo.test.mjs")
    assert_true("node:test" in tests, "扩展测试未使用 node:test")
    package = _json("extension/package.json")
    assert_true("test" in (package.get("scripts") or {}), "extension package.json 缺少 test 脚本")
    return "仓库解析 / 页面元数据提取 / node:test 用例"


def check_extension_edge() -> str:
    migration = _read("edge/migrations/0022_extension_tokens.sql")
    for needle in ("CREATE TABLE IF NOT EXISTS extension_tokens", "token_hash", "revoked_at"):
        assert_true(needle in migration, f"迁移缺少 {needle}")
    assert_true(
        "CREATE TABLE IF NOT EXISTS extension_tokens" in _read("docs/assets/d1-schema.sql"),
        "d1-schema 缺少 extension_tokens",
    )
    route = _read("edge/src/routes/extension.ts")
    for endpoint in ("'/tokens'", "'/tokens/:id'", "'/me'", "'/check'", "'/bookmark'"):
        assert_true(endpoint in route, f"extension 路由缺少 {endpoint}")
    index = _read("edge/src/index.ts")
    assert_true("app.route('/api/extension'" in index, "index.ts 未挂载扩展路由")
    assert_true("chrome-extension" in index and "moz-extension" in index, "CORS 未允许扩展来源")
    _read("admin/src/features/extension/index.tsx")
    _read("admin/src/routes/_authenticated/settings/extension.tsx")
    return "迁移 0022 / 6 个接口 / CORS / admin 令牌页"


# ---------------------------------------------------------------------------
# M8-03 Telegram Bot
# ---------------------------------------------------------------------------
def check_telegram_bot() -> str:
    bot = _read("edge/src/telegram/bot.ts")
    for fn in (
        "parseTelegramCommand",
        "escapeTelegramHtml",
        "chunkTelegramMessage",
        "buildFavoritesMessage",
        "buildRecommendationsMessage",
        "buildTrendingMessage",
    ):
        assert_true(f"function {fn}" in bot, f"bot.ts 缺少 {fn}")
    assert_true("TELEGRAM_MAX_MESSAGE_CHARS = 4096" in bot, "缺少 4096 上限")
    assert_true("TELEGRAM_MESSAGE_TARGET_CHARS = 3800" in bot, "缺少 3800 分片目标")
    for command in ("favorites", "recommend", "trending", "link", "unlink", "help"):
        assert_true(command in bot, f"缺少命令 {command}")
    return "命令解析 / HTML 转义 / 3800 分片 / 六类消息"


def check_telegram_edge() -> str:
    migration = _read("edge/migrations/0021_telegram_bot.sql")
    for needle in ("CREATE TABLE IF NOT EXISTS telegram_links", "CREATE TABLE IF NOT EXISTS telegram_link_codes", "code_hash"):
        assert_true(needle in migration, f"迁移缺少 {needle}")
    route = _read("edge/src/routes/telegram.ts")
    for endpoint in ("'/webhook'", "'/status'", "'/link-code'", "'/link'"):
        assert_true(endpoint in route, f"telegram 路由缺少 {endpoint}")
    index = _read("edge/src/index.ts")
    assert_true("app.route('/api/telegram'" in index, "index.ts 未挂载 Telegram 路由")
    rate = _read("edge/src/security/rate-limit.ts")
    assert_true("pathname === '/api/telegram/webhook'" in rate, "webhook 未豁免 IP 限流")
    wrangler = _read("edge/wrangler.toml")
    assert_true("TELEGRAM_BOT_USERNAME" in wrangler, "wrangler 缺少 TELEGRAM_BOT_USERNAME")
    assert_true("TELEGRAM_API_BASE" in wrangler, "wrangler 缺少 TELEGRAM_API_BASE")
    _read("admin/src/features/settings/notifications/telegram-bot-panel.tsx")
    _read("admin/src/features/settings/notifications/telegram-bot-api.ts")
    return "迁移 0021 / 4 个接口 / webhook 免限流 / admin 面板"


# ---------------------------------------------------------------------------
# M8-04 快捷入口评估
# ---------------------------------------------------------------------------
def check_quick_entry_eval() -> str:
    from app.services.quick_entry_eval import (
        API_REQUIREMENTS,
        build_evaluation,
        render_contract,
        render_markdown,
    )

    report = build_evaluation()
    assert_equal(report.primary, "raycast", "首选平台")
    assert_equal(report.secondary, "shortcuts", "次选平台")
    assert_equal(len(report.platforms), 6, "候选平台数")
    assert_equal(report.platforms[0].weighted_score, 4.1, "Raycast 加权分")
    assert_equal(report.platforms[1].weighted_score, 3.95, "快捷指令加权分")
    assert_equal(report.platforms[0].grade, "A", "Raycast 等级")
    assert_equal(len(API_REQUIREMENTS), 16, "M8-05 前置能力数")
    assert_equal(len(report.api_requirements), 16, "API 就绪度条目数")
    assert_equal(sum(1 for item in report.api_requirements if item.ready), 0, "API 就绪数")
    contract = render_contract(report)
    assert_equal(contract.get("schema"), "openfactory.quick-entry.v1", "契约 schema")
    assert_equal(len(contract.get("endpoints") or []), 10, "契约端点数量")
    markdown = render_markdown(report)
    assert_true("Raycast" in markdown and "M8-05" in markdown, "报告内容异常")
    return f"raycast={report.platforms[0].weighted_score} shortcuts={report.platforms[1].weighted_score} api=0/16"


def check_quick_entry_assets() -> str:
    report = _read("docs/architecture/quick-entry-evaluation.md")
    assert_true("Raycast" in report and "4.10" in report, "评估报告内容异常")
    contract = _json("docs/assets/quick-entry-api-contract.json")
    assert_equal(contract.get("schema"), "openfactory.quick-entry.v1", "归档契约 schema")
    _read("vps/app/quick_entry_eval.py")
    _read("vps/tests/test_quick_entry_eval.py")
    return "报告 / 契约 / CLI / 测试齐全"


# ---------------------------------------------------------------------------
# 跨切面 / 迁移 / 文档
# ---------------------------------------------------------------------------
def check_cross_cutting() -> str:
    index = _read("edge/src/index.ts")
    for route in ("/api/extension", "/api/telegram"):
        assert_true(f"app.route('{route}'" in index, f"index.ts 未挂载 {route}")
    route_tree = _read("admin/src/routeTree.gen.ts")
    assert_true("'/settings/extension'" in route_tree, "routeTree 缺少扩展令牌页")
    for route in ("/reports", "/updates", "/star-trends", "/model-routing", "/rerank"):
        assert_true(route in route_tree, f"routeTree 缺少 {route}")
    return "edge 路由挂载 + admin 路由树完整"


def check_migrations() -> str:
    names = {path.name for path in (REPO_ROOT / "edge" / "migrations").glob("00*.sql")}
    for expected in ("0021_telegram_bot.sql", "0022_extension_tokens.sql"):
        assert_true(expected in names, f"缺少迁移 {expected}")
    assert_true("0016_extension_tokens.sql" not in names, "扩展迁移仍与 M7-01 重号")
    schema = _read("docs/assets/d1-schema.sql")
    for table in ("extension_tokens", "telegram_links", "telegram_link_codes"):
        assert_true(f"CREATE TABLE IF NOT EXISTS {table}" in schema, f"d1-schema 缺少 {table}")
    return "M8 迁移 0021/0022 编号唯一，D1 schema 同步"


def check_docs_status() -> str:
    backlog = _read("docs/requirements/backlog.md")
    for item in ("M8-01", "M8-02", "M8-03", "M8-04", "M8-08"):
        line = next((row for row in backlog.splitlines() if row.startswith(f"| {item} |")), "")
        assert_true("✅" in line, f"backlog {item} 未标记完成")
    for item in ("M8-05", "M8-06", "M8-07"):
        line = next((row for row in backlog.splitlines() if row.startswith(f"| {item} |")), "")
        assert_true("✅" not in line, f"backlog {item} 不应标记完成")
    _read("docs/planning/acceptance-m8.md")
    _read("docs/planning/plan-req-202610-0977-m8-acceptance.md")
    return "backlog 状态正确，验收结论与计划文档齐全"


def check_gaps() -> None:
    branches = {
        "M8-05": ("feat/req-202610-0974-open-api", "开放 API（个人令牌）"),
        "M8-06": ("feat/req-202610-0975-cli-tool", "CLI 工具（命令行查询 / 收藏）"),
        "M8-07": ("feat/req-202610-0976-offline-pwa-local-data", "离线可用（PWA 缓存 + 本地数据）"),
    }
    for cid, (branch, title) in branches.items():
        try:
            merged = (
                subprocess.run(
                    ["git", "merge-base", "--is-ancestor", branch, "HEAD"],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    timeout=15,
                ).returncode
                == 0
            )
        except Exception:  # noqa: BLE001 - 分支不存在按缺口处理
            merged = False
        if merged:
            RESULTS.append(
                {
                    "id": f"{cid}-GAP",
                    "title": f"{title}（已合并，待平台状态确认）",
                    "status": "PASS",
                    "detail": f"{branch} 已包含在验收分支",
                    "durationMs": 0.0,
                }
            )
        else:
            gap(
                f"{cid}-GAP",
                f"{title}（平台 pending）",
                f"{branch} 未合并，需该需求交付后补充验收",
            )


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------
def summarize() -> dict[str, int]:
    counts = {"PASS": 0, "FAIL": 0, "GAP": 0}
    for item in RESULTS:
        status = str(item["status"])
        counts[status] = counts.get(status, 0) + 1
    return counts


def git_info() -> tuple[str, str]:
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return branch, commit
    except Exception:  # noqa: BLE001 - 报告不因 git 缺失失败
        return "unknown", "unknown"


def build_markdown(meta: dict[str, str]) -> str:
    rows = "\n".join(
        f"| {item['id']} | {item['title']} | {item['status']} | {item['detail']} | {item['durationMs']}ms |"
        for item in RESULTS
    )
    summary = summarize()
    if summary["FAIL"]:
        conclusion = "存在失败项，M8 验收不通过"
    elif summary["GAP"]:
        conclusion = (
            "M8-01~04 已交付能力全部通过；M8-05~07 平台状态仍为 pending，"
            "本轮判定为部分验收（有条件通过）"
        )
    else:
        conclusion = "全部通过，M8 验收通过"
    return f"""# M8 验收报告（自动生成）

- 生成时间：{meta['finishedAt']}
- 分支 / 提交：{meta['branch']} / {meta['commit']}
- 运行环境：{meta['platform']} · Python {meta['python']}
- 验收方式：跨分支静态资产检查 + M8-04 评估工具实跑 + 缺口登记
- 判定口径：PASS 通过 · FAIL 行为错误 · GAP 未交付缺口（不计入通过率）

## 检查结果

| # | 检查 | 结果 | 说明 | 耗时 |
| --- | --- | --- | --- | --- |
{rows}

## 汇总

- PASS：{summary['PASS']}
- FAIL：{summary['FAIL']}
- GAP：{summary['GAP']}
- 结论：{conclusion}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="M8 验收脚本")
    parser.add_argument("--strict", action="store_true", help="存在 GAP 或 FAIL 时返回非零")
    parser.add_argument("--report-md", default=None, help="Markdown 报告输出路径")
    parser.add_argument("--report-json", default=None, help="JSON 报告输出路径")
    args = parser.parse_args()

    print("• M8-01 PWA 与移动端…")
    check("M8-A01", "M8-01 PWA manifest 与图标", check_pwa_manifest)
    check("M8-A02", "M8-01 Service Worker 与离线兜底", check_pwa_service_worker)
    check("M8-A03", "M8-01 安装引导与移动端导航", check_pwa_integration)

    print("• M8-02 浏览器扩展…")
    check("M8-B01", "M8-02 MV3 manifest", check_extension_manifest)
    check("M8-B02", "M8-02 扩展核心与单测", check_extension_core)
    check("M8-B03", "M8-02 edge 令牌接口与迁移", check_extension_edge)

    print("• M8-03 Telegram Bot…")
    check("M8-C01", "M8-03 Bot 命令纯函数", check_telegram_bot)
    check("M8-C02", "M8-03 webhook 路由与迁移", check_telegram_edge)

    print("• M8-04 快捷入口评估…")
    check("M8-D01", "M8-04 评估工具实跑", check_quick_entry_eval)
    check("M8-D02", "M8-04 报告与契约资产", check_quick_entry_assets)

    print("• 跨切面检查…")
    check("M8-S01", "edge / admin 路由集成", check_cross_cutting)
    check("M8-S02", "M8 迁移编号与 D1 schema", check_migrations)
    check("M8-S03", "需求与验收文档状态", check_docs_status)
    check_gaps()

    summary = summarize()
    print(f"\n汇总：PASS {summary['PASS']} · FAIL {summary['FAIL']} · GAP {summary['GAP']}")

    branch, commit = git_info()
    meta = {
        "branch": branch,
        "commit": commit,
        "finishedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "platform": platform.platform(),
        "python": platform.python_version(),
    }
    if args.report_md:
        target = (REPO_ROOT / args.report_md).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(build_markdown(meta), encoding="utf-8")
        print(f"• 已写入 Markdown 报告：{target}")
    if args.report_json:
        target = (REPO_ROOT / args.report_json).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"meta": meta, "results": RESULTS}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"• 已写入 JSON 报告：{target}")

    if summary["FAIL"] > 0 or (args.strict and summary["GAP"] > 0):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
