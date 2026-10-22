"""依赖分析测试（M6-07，不访问网络）。

覆盖：8 类清单解析、名称规范化、异常文本降级、扫描覆盖写入 / 失败保留旧数据、
聚合统计与仓库过滤、内部 API 契约。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db import SessionLocal, init_db
from app.main import app
from app.models import MyRepository, RepoDependency, RepoDependencyScan
from app.services.dependency_analysis import (
    aggregate_dependencies,
    normalize_name,
    parse_cargo_toml,
    parse_composer_json,
    parse_gemfile,
    parse_go_mod,
    parse_manifest,
    parse_package_json,
    parse_pom_xml,
    parse_pyproject_toml,
    parse_requirements_txt,
    scan_repositories,
)


@pytest.fixture()
def db():
    init_db()
    session = SessionLocal()

    def cleanup() -> None:
        session.execute(delete(RepoDependency).where(RepoDependency.repo_id.like("dep-test/%")))
        session.execute(
            delete(RepoDependencyScan).where(RepoDependencyScan.repo_id.like("dep-test/%"))
        )
        session.execute(delete(MyRepository).where(MyRepository.id.like("dep-test/%")))
        session.commit()

    cleanup()
    yield session
    cleanup()
    session.close()


def _repo(repo_id: str, language: str, stars: int = 1) -> MyRepository:
    return MyRepository(
        id=repo_id,
        platform="github",
        name=repo_id.split("/")[-1],
        description="",
        html_url=f"https://example.com/{repo_id}",
        stars=stars,
        language=language,
    )


# ---------------------------------------------------------------------------
# 解析器
# ---------------------------------------------------------------------------


def test_parse_package_json_splits_runtime_and_dev() -> None:
    text = """
    {
      "dependencies": {"react": "^18.2.0", "@tanstack/react-query": "5.0.0"},
      "peerDependencies": {"react-dom": "^18.0.0"},
      "devDependencies": {"typescript": "~5.6.0", "vitest": "2.1.0"}
    }
    """
    deps = parse_package_json(text)
    by_name = {dep.name: dep for dep in deps}
    assert by_name["react"].kind == "runtime"
    assert by_name["@tanstack/react-query"].version == "5.0.0"
    assert by_name["react-dom"].kind == "runtime"
    assert by_name["typescript"].kind == "dev"
    assert by_name["vitest"].kind == "dev"
    assert all(dep.ecosystem == "npm" for dep in deps)


def test_parse_requirements_txt_skips_options_and_extras() -> None:
    text = """
    # comment
    -r base.txt
    --index-url https://example.com/simple
    Flask==3.0.0
    requests[security]>=2.31
    My_Package==1.0 ; python_version > "3.10"
    git+https://example.com/repo.git
    """
    deps = parse_requirements_txt(text)
    names = [dep.name for dep in deps]
    assert names == ["flask", "requests", "my-package"]
    assert deps[0].version == "==3.0.0"
    assert deps[1].version == ">=2.31"
    assert deps[2].version == "==1.0"


def test_parse_pyproject_toml_pep621_and_poetry() -> None:
    text = """
    [project]
    name = "demo"
    dependencies = ["httpx>=0.27", "pydantic[email]==2.9.0"]

    [project.optional-dependencies]
    test = ["pytest>=8"]

    [tool.poetry.dependencies]
    python = "^3.12"
    fastapi = "^0.115"

    [tool.poetry.group.dev.dependencies]
    ruff = "^0.6"
    """
    deps = parse_pyproject_toml(text)
    by_name = {dep.name: dep for dep in deps}
    assert by_name["httpx"].kind == "runtime"
    assert by_name["pydantic"].version == "==2.9.0"
    assert by_name["pytest"].kind == "dev"
    assert by_name["fastapi"].version == "^0.115"
    assert by_name["ruff"].kind == "dev"
    assert "python" not in by_name


def test_parse_go_mod_blocks_and_single_lines() -> None:
    text = """
    module example.com/demo

    go 1.22

    require github.com/gin-gonic/gin v1.10.0

    require (
        github.com/stretchr/testify v1.9.0 // indirect
        golang.org/x/sync v0.8.0
    )
    """
    deps = parse_go_mod(text)
    by_name = {dep.name: dep for dep in deps}
    assert by_name["github.com/gin-gonic/gin"].version == "v1.10.0"
    assert by_name["github.com/stretchr/testify"].version == "v1.9.0"
    assert by_name["golang.org/x/sync"].version == "v0.8.0"
    assert len(deps) == 3


def test_parse_cargo_toml_sections() -> None:
    text = """
    [package]
    name = "demo"

    [dependencies]
    serde = { version = "1.0", features = ["derive"] }
    tokio = "1.40"

    [dev-dependencies]
    criterion = "0.5"
    """
    deps = parse_cargo_toml(text)
    by_name = {dep.name: dep for dep in deps}
    assert by_name["serde"].version == "1.0"
    assert by_name["tokio"].kind == "runtime"
    assert by_name["criterion"].kind == "dev"


def test_parse_pom_xml_scope() -> None:
    text = """
    <project xmlns="http://maven.apache.org/POM/4.0.0">
      <dependencies>
        <dependency>
          <groupId>org.springframework</groupId>
          <artifactId>spring-core</artifactId>
          <version>6.1.0</version>
        </dependency>
        <dependency>
          <groupId>org.junit.jupiter</groupId>
          <artifactId>junit-jupiter</artifactId>
          <version>5.10.0</version>
          <scope>test</scope>
        </dependency>
      </dependencies>
    </project>
    """
    deps = parse_pom_xml(text)
    by_name = {dep.name: dep for dep in deps}
    assert by_name["org.springframework:spring-core"].kind == "runtime"
    assert by_name["org.junit.jupiter:junit-jupiter"].kind == "dev"


def test_parse_gemfile_groups() -> None:
    text = """
    source "https://rubygems.org"

    gem "rails", "~> 7.1"
    gem "puma", ">= 6.0"

    group :development, :test do
      gem "rspec", "~> 3.13"
      gem "rubocop", require: false
    end
    """
    deps = parse_gemfile(text)
    by_name = {dep.name: dep for dep in deps}
    assert by_name["rails"].version == "~> 7.1"
    assert by_name["puma"].kind == "runtime"
    assert by_name["rspec"].kind == "dev"
    assert by_name["rubocop"].kind == "dev"


def test_parse_composer_json_sections() -> None:
    text = """
    {
      "require": {"php": ">=8.2", "laravel/framework": "^11.0"},
      "require-dev": {"phpunit/phpunit": "^11.0"}
    }
    """
    deps = parse_composer_json(text)
    by_name = {dep.name: dep for dep in deps}
    assert by_name["laravel/framework"].kind == "runtime"
    assert by_name["phpunit/phpunit"].kind == "dev"


def test_malformed_inputs_and_normalize_name() -> None:
    assert parse_package_json("{not json") == []
    assert parse_pyproject_toml("[project") == []
    assert parse_go_mod("") == []
    assert parse_cargo_toml("[[[") == []
    assert parse_pom_xml("<project>") == []
    assert parse_gemfile("") == []
    assert parse_composer_json("[]") == []
    assert parse_manifest("unknown.lock", "whatever") == []

    assert normalize_name("pypi", "My_Package.Name") == "my-package-name"
    assert normalize_name("npm", "@Scope/Name") == "@Scope/Name"


# ---------------------------------------------------------------------------
# 扫描与聚合
# ---------------------------------------------------------------------------


PACKAGE_JSON = """
{
  "dependencies": {"react": "^18.2.0"},
  "devDependencies": {"typescript": "~5.6.0"}
}
"""

REQUIREMENTS = """
Flask==3.0.0
requests>=2.31
"""


def _fetcher(repo_id: str, manifest: str):
    if repo_id == "dep-test/web" and manifest == "package.json":
        return PACKAGE_JSON
    if repo_id == "dep-test/api" and manifest == "requirements.txt":
        return REQUIREMENTS
    return None


def test_scan_writes_dependencies_and_is_idempotent(db) -> None:
    db.add_all([_repo("dep-test/web", "TypeScript", 10), _repo("dep-test/api", "Python", 5)])
    db.commit()

    first = scan_repositories(db, ["dep-test/web", "dep-test/api"], force=True, fetcher=_fetcher)
    assert first["status"] == "ok"
    assert first["scanned"] == 2
    assert first["ok"] == 2
    assert first["dependencies"] == 4

    rows = db.query(RepoDependency).filter(RepoDependency.repo_id.like("dep-test/%")).all()
    assert len(rows) == 4
    assert {row.name for row in rows} == {"react", "typescript", "flask", "requests"}

    second = scan_repositories(db, ["dep-test/web"], force=True, fetcher=_fetcher)
    assert second["dependencies"] == 2
    rows = db.query(RepoDependency).filter(RepoDependency.repo_id == "dep-test/web").all()
    assert len(rows) == 2  # 覆盖写入，不重复

    scan = db.get(RepoDependencyScan, "dep-test/web")
    assert scan is not None
    assert scan.status == "ok"
    assert scan.manifests == "package.json"
    assert scan.dependency_count == 2


def test_scan_marks_no_manifest_and_failure_keeps_old_data(db) -> None:
    db.add_all(
        [
            _repo("dep-test/empty", "Go"),
            _repo("dep-test/broken", "Rust"),
        ]
    )
    db.commit()

    # 先成功扫描 broken，再模拟全部清单拉取失败
    scan_repositories(db, ["dep-test/broken"], force=True, fetcher=_fetcher)
    db.add(
        RepoDependency(
            id="keep-old",
            repo_id="dep-test/broken",
            ecosystem="cargo",
            name="serde",
            version="1.0",
            kind="runtime",
            manifest="Cargo.toml",
        )
    )
    db.commit()

    empty = scan_repositories(db, ["dep-test/empty"], force=True, fetcher=_fetcher)
    assert empty["noManifest"] == 1
    assert db.get(RepoDependencyScan, "dep-test/empty").status == "no_manifest"

    def failing(repo_id: str, manifest: str):
        raise RuntimeError("network down")

    failed = scan_repositories(db, ["dep-test/broken"], force=True, fetcher=failing)
    assert failed["failed"] == 1
    assert db.get(RepoDependencyScan, "dep-test/broken").status == "failed"
    assert db.get(RepoDependency, "keep-old") is not None  # 旧数据保留


def test_aggregate_dependencies_stats_and_filter(db) -> None:
    db.add_all(
        [
            _repo("dep-test/web", "TypeScript", 10),
            _repo("dep-test/api", "Python", 5),
            _repo("dep-test/idle", "Python", 1),
        ]
    )
    db.commit()
    scan_repositories(db, ["dep-test/web", "dep-test/api"], force=True, fetcher=_fetcher)

    result = aggregate_dependencies(db, ["dep-test/web", "dep-test/api", "dep-test/idle"], top=10)
    assert result["summary"]["repos"] == 3
    assert result["summary"]["analyzed"] == 2
    assert result["summary"]["pending"] == 1
    assert result["summary"]["dependencyRows"] == 4
    assert result["summary"]["uniqueDependencies"] == 4

    languages = {item["language"]: item for item in result["techStack"]}
    assert languages["Python"]["count"] == 2
    assert languages["TypeScript"]["count"] == 1
    assert round(languages["Python"]["percent"], 2) == 0.67

    ecosystems = {item["ecosystem"]: item for item in result["ecosystems"]}
    assert ecosystems["npm"]["repos"] == 1
    assert ecosystems["pypi"]["dependencies"] == 2

    dep = next(item for item in result["dependencies"] if item["name"] == "react")
    assert dep["ecosystem"] == "npm"
    assert dep["repoCount"] == 1
    assert dep["coverage"] == 0.5
    assert dep["languages"] == [{"language": "TypeScript", "count": 1}]
    assert any(link["dependency"] == "react" and link["strength"] == 1.0 for link in result["links"])

    only_web = aggregate_dependencies(db, ["dep-test/web"], top=10)
    assert only_web["summary"]["repos"] == 1
    assert only_web["summary"]["dependencyRows"] == 2
    assert {item["name"] for item in only_web["dependencies"]} == {"react", "typescript"}


def test_analysis_api_contract(db, monkeypatch) -> None:
    db.add(_repo("dep-test/web", "TypeScript", 10))
    db.commit()
    scan_repositories(db, ["dep-test/web"], force=True, fetcher=_fetcher)

    with TestClient(app) as client:
        ok = client.get("/api/analysis/dependencies", params={"repoIds": "dep-test/web", "top": 5})
        assert ok.status_code == 200
        body = ok.json()
        assert body["summary"]["repos"] == 1
        assert body["summary"]["dependencyRows"] == 2
        assert body["dependencies"][0]["name"] in {"react", "typescript"}

        def fake_scan(db_session, repo_ids, force=False, limit=0):
            return {
                "status": "ok",
                "scanned": 1,
                "ok": 1,
                "noManifest": 0,
                "failed": 0,
                "dependencies": 2,
                "repos": [{"repoId": "dep-test/web", "status": "ok"}],
            }

        monkeypatch.setattr("app.api.analysis.scan_repositories", fake_scan)
        refreshed = client.post(
            "/api/analysis/dependencies/refresh",
            json={"repoIds": ["dep-test/web"], "force": True},
        )
        assert refreshed.status_code == 200
        assert refreshed.json()["dependencies"] == 2
        assert refreshed.json()["repos"][0]["repoId"] == "dep-test/web"
