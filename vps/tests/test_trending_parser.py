"""GitHub Trending 解析测试：内联 HTML 固定样例，无网络。"""
from __future__ import annotations

from app.services.trending_crawler import parse_trending_html

HTML_FIXTURE = """
<div class="Box">
  <article class="Box-row">
    <h2 class="h3 lh-condensed">
      <a href="/openai/whisper">
        <span class="text-normal">openai /</span>
        whisper
      </a>
    </h2>
    <p class="col-9 color-fg-muted my-1 pr-4">
      Robust Speech Recognition via Large-Scale Weak Supervision
    </p>
    <div class="f6 color-fg-muted mt-2">
      <span itemprop="programmingLanguage">Python</span>
      <a href="/openai/whisper/stargazers" class="Link--muted d-inline-block mr-3">
        65,432
      </a>
      <span class="d-inline-block float-sm-right">
        1,234 stars today
      </span>
    </div>
  </article>

  <article class="Box-row">
    <h2 class="h3 lh-condensed">
      <a href="/golang/go">
        <span class="text-normal">golang /</span>
        go
      </a>
    </h2>
    <p class="col-9 color-fg-muted my-1 pr-4">
      The Go programming language
    </p>
    <div class="f6 color-fg-muted mt-2">
      <span itemprop="programmingLanguage">Go</span>
      <a href="/golang/go/stargazers" class="Link--muted d-inline-block mr-3">
        123,456
      </a>
      <span class="d-inline-block float-sm-right">
        987 stars today
      </span>
    </div>
  </article>
</div>
"""


def test_parse_trending_html_two_repos() -> None:
    items = parse_trending_html(HTML_FIXTURE)
    assert len(items) == 2

    first = items[0]
    assert first["id"] == "openai/whisper"
    assert first["platform"] == "github"
    assert first["owner"] == "openai"
    assert first["name"] == "whisper"
    assert first["html_url"] == "https://github.com/openai/whisper"
    assert "Speech Recognition" in first["description"]
    assert first["language"] == "Python"
    assert first["stars_today"] == 1234
    assert first["stars"] == 65432

    second = items[1]
    assert second["id"] == "golang/go"
    assert second["name"] == "go"
    assert second["language"] == "Go"
    assert second["stars_today"] == 987
    assert second["stars"] == 123456


def test_parse_trending_html_tolerates_missing_fields() -> None:
    html = """
    <article class="Box-row">
      <h2><a href="/foo/bar">foo / bar</a></h2>
    </article>
    <div>这里没有 article 结构</div>
    """
    items = parse_trending_html(html)
    assert len(items) == 1
    item = items[0]
    assert item["id"] == "foo/bar"
    assert item["description"] == ""
    assert item["language"] == ""
    assert item["stars_today"] == 0
    assert item["stars"] == 0


def test_parse_trending_html_handles_garbage() -> None:
    assert parse_trending_html("") == []
    assert parse_trending_html("<html><body>nothing</body></html>") == []
    # 非 owner/repo 形状的链接应被跳过
    html = '<article class="Box-row"><h2><a href="/about">About</a></h2></article>'
    assert parse_trending_html(html) == []
