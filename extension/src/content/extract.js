/**
 * 在目标页面上下文执行：提取仓库页可见元数据。
 *
 * 该函数会被 chrome.scripting.executeScript 序列化后注入页面，
 * 因此必须是自包含的（不能引用模块外的变量 / 函数）。
 */
export function extractRepoPage() {
  function textOf(selector) {
    const el = document.querySelector(selector);
    if (!el) return '';
    return (el.textContent || '').replace(/\s+/g, ' ').trim();
  }

  function attrOrText(selector, attrs) {
    const el = document.querySelector(selector);
    if (!el) return '';
    for (const attr of attrs) {
      const value = el.getAttribute(attr);
      if (value && value.trim()) return value.trim();
    }
    return (el.textContent || '').replace(/\s+/g, ' ').trim();
  }

  function meta(selector) {
    const el = document.querySelector(selector);
    return el ? (el.getAttribute('content') || '').trim() : '';
  }

  const descriptionCandidates = [
    meta('meta[name="description"]'),
    meta('meta[property="og:description"]'),
    meta('meta[name="twitter:description"]'),
    textOf('[data-testid="repository-description"]'),
    textOf('p.f4.my-3'),
    textOf('.project-description'),
    textOf('.repository-description'),
  ].filter(Boolean);

  const language =
    textOf('[itemprop="programmingLanguage"]') ||
    textOf('.project-language') ||
    textOf('.repository-language') ||
    textOf('[data-testid="repository-language"]');

  const starsText =
    attrOrText('#repo-stars-counter-star', ['title', 'aria-label']) ||
    attrOrText('#star-count', ['title', 'aria-label']) ||
    attrOrText('.star-count', ['title', 'aria-label']) ||
    attrOrText('.stars-count', ['title', 'aria-label']);

  const forksText =
    attrOrText('#repo-network-counter', ['title', 'aria-label']) ||
    attrOrText('.fork-count', ['title', 'aria-label']) ||
    attrOrText('.forks-count', ['title', 'aria-label']);

  const canonical = document.querySelector('link[rel="canonical"]');
  const ogUrl = meta('meta[property="og:url"]');

  return {
    url: location.href,
    canonicalUrl: canonical ? canonical.href : ogUrl,
    title: document.title,
    descriptionCandidates,
    language,
    starsText,
    forksText,
    host: location.hostname,
  };
}
