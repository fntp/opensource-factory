"""README 摘要批量管线测试（无网络）。"""
from __future__ import annotations

from uuid import uuid4

from app.db import SessionLocal, init_db
from app.models import MyRepository
from app.services import summarizer
from app.services.summary_pipeline import (
    RepoSummaryOutcome,
    summarize_one,
    summarize_repositories,
    writeback_summaries,
)


def test_summarize_with_source_prefers_ollama(monkeypatch) -> None:
    monkeypatch.setattr(summarizer, "_summarize_with_ollama", lambda text, max_chars: "本地摘要")
    monkeypatch.setattr(summarizer, "_summarize_with_deepseek", lambda text, max_chars: "云端摘要")
    result = summarizer.summarize_with_source("README 正文")
    assert result.text == "本地摘要"
    assert result.source == "ollama"


def test_summarize_with_source_falls_back_to_deepseek(monkeypatch) -> None:
    monkeypatch.setattr(summarizer, "_summarize_with_ollama", lambda text, max_chars: "")
    monkeypatch.setattr(summarizer, "_summarize_with_deepseek", lambda text, max_chars: "云端摘要")
    result = summarizer.summarize_with_source("README 正文")
    assert result.text == "云端摘要"
    assert result.source == "deepseek"


def test_summarize_with_source_falls_back_to_truncated(monkeypatch) -> None:
    monkeypatch.setattr(summarizer, "_summarize_with_ollama", lambda text, max_chars: "")
    monkeypatch.setattr(summarizer, "_summarize_with_deepseek", lambda text, max_chars: "")
    result = summarizer.summarize_with_source("README 正文" * 100, max_chars=50)
    assert result.source == "truncated"
    assert result.text.startswith("（LLM 暂不可用")
    assert len(result.text) <= 100


def test_summarize_with_source_empty_input() -> None:
    result = summarizer.summarize_with_source("   ")
    assert result.source == "empty"
    assert result.text == ""


def test_summarize_one_cleans_readme(monkeypatch) -> None:
    captured: dict[str, str] = {}

    async def fake_get_readme(token: str, repo_id: str) -> str:
        return "<!-- comment -->\n# Demo\n[![badge](https://img.example/b.svg)](https://x)\n正文"

    def fake_summarize(text: str, *, max_chars: int):
        captured["text"] = text
        return summarizer.SummaryResult(text="摘要", source="ollama", model="m")

    monkeypatch.setattr("app.services.summary_pipeline.get_readme", fake_get_readme)
    monkeypatch.setattr("app.services.summary_pipeline.summarize_with_source", fake_summarize)

    outcome = summarize_one("owner/demo")
    assert outcome.summary == "摘要"
    assert outcome.source == "ollama"
    assert "comment" not in captured["text"]
    assert "img.example" not in captured["text"]
    assert "正文" in captured["text"]


def _insert_repo(repo_id: str, *, summary: str | None = None) -> None:
    db = SessionLocal()
    try:
        db.add(
            MyRepository(
                id=repo_id,
                platform="github",
                name=repo_id.split("/")[-1],
                description="demo",
                html_url=f"https://github.com/{repo_id}",
                stars=1,
                readme_summary=summary,
            )
        )
        db.commit()
    finally:
        db.close()


def _delete_repos(repo_ids: list[str]) -> None:
    db = SessionLocal()
    try:
        for repo_id in repo_ids:
            row = db.get(MyRepository, repo_id)
            if row is not None:
                db.delete(row)
        db.commit()
    finally:
        db.close()


def test_summarize_repositories_batches_and_persists(monkeypatch) -> None:
    init_db()
    suffix = uuid4().hex[:8]
    repo_ids = [f"owner/demo-{suffix}-{i}" for i in range(3)]
    for repo_id in repo_ids:
        _insert_repo(repo_id)

    def fake_summarize_one(repo_id: str, *, token: str = "", max_chars: int = 800):
        return RepoSummaryOutcome(repo_id=repo_id, summary=f"摘要-{repo_id}", source="ollama")

    monkeypatch.setattr("app.services.summary_pipeline.summarize_one", fake_summarize_one)
    monkeypatch.setattr(
        "app.services.summary_pipeline.writeback_summaries",
        lambda items: {"status": "skipped", "reason": "test"},
    )

    stats = summarize_repositories(repo_ids=repo_ids, batch_size=2, sleep_fn=lambda _: None)
    assert stats["total"] == 3
    assert stats["summarized"] == 3
    assert stats["sources"] == {"ollama": 3}

    db = SessionLocal()
    try:
        summaries = [db.get(MyRepository, repo_id).readme_summary for repo_id in repo_ids]
    finally:
        db.close()
    assert summaries == [f"摘要-{repo_id}" for repo_id in repo_ids]

    _delete_repos(repo_ids)


def test_summarize_repositories_skips_existing_unless_force(monkeypatch) -> None:
    init_db()
    repo_id = f"owner/existing-{uuid4().hex[:8]}"
    _insert_repo(repo_id, summary="已有摘要")

    calls: list[str] = []

    def fake_summarize_one(repo_id: str, *, token: str = "", max_chars: int = 800):
        calls.append(repo_id)
        return RepoSummaryOutcome(repo_id=repo_id, summary="新摘要", source="ollama")

    monkeypatch.setattr("app.services.summary_pipeline.summarize_one", fake_summarize_one)
    monkeypatch.setattr(
        "app.services.summary_pipeline.writeback_summaries",
        lambda items: {"status": "skipped", "reason": "test"},
    )

    skipped = summarize_repositories(repo_ids=[repo_id], sleep_fn=lambda _: None)
    assert skipped["total"] == 0
    assert calls == []

    forced = summarize_repositories(repo_ids=[repo_id], force=True, sleep_fn=lambda _: None)
    assert forced["total"] == 1
    assert calls == [repo_id]

    _delete_repos([repo_id])


def test_writeback_summaries_skips_without_edge_url(monkeypatch) -> None:
    class _Settings:
        EDGE_BASE_URL = ""
        INTERNAL_TOKEN = ""

    monkeypatch.setattr("app.services.summary_pipeline.get_settings", lambda: _Settings())
    result = writeback_summaries([{"repoId": "owner/demo", "summary": "摘要"}])
    assert result["status"] == "skipped"
