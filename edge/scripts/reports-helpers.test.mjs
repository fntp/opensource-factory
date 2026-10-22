import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildReport,
  buildReportId,
  formatCount,
  isWithinPeriod,
  parseDateOnly,
  resolveReportPeriod,
} from '../src/reports/generate.ts';

const NOW = new Date('2026-10-22T10:00:00Z');

function sampleData() {
  return {
    repos: [
      {
        id: 'acme/new-repo',
        name: 'new-repo',
        description: '本周新收藏的项目',
        html_url: 'https://github.com/acme/new-repo',
        stars: 120,
        language: 'TypeScript',
        category_id: 'c1',
        created_at: '2026-10-20 08:00:00',
        owner: 'acme',
      },
      {
        id: 'acme/old-repo',
        name: 'old-repo',
        description: '很久以前收藏的项目',
        html_url: 'https://github.com/acme/old-repo',
        stars: 500,
        language: 'Python',
        category_id: 'c2',
        created_at: '2025-01-01 08:00:00',
        owner: 'acme',
      },
    ],
    categories: [
      { id: 'c1', name: 'AI' },
      { id: 'c2', name: 'Infra' },
    ],
    recommendations: [
      {
        id: 'rec-1',
        repo_id: 'other/good-repo',
        owner: 'other',
        name: 'good-repo',
        description: '值得关注',
        language: 'Go',
        stars: 900,
        score: 0.91,
        reason: '与你收藏的 AI 项目相似',
        url: 'https://github.com/other/good-repo',
        status: 'new',
        created_at: '2026-10-21 09:00:00',
      },
      {
        id: 'rec-2',
        repo_id: 'other/dismissed-repo',
        owner: 'other',
        name: 'dismissed-repo',
        description: '已忽略',
        language: 'Go',
        stars: 100,
        score: 0.99,
        reason: null,
        url: 'https://github.com/other/dismissed-repo',
        status: 'dismissed',
        created_at: '2026-10-21 09:00:00',
      },
      {
        id: 'rec-3',
        repo_id: 'other/old-rec',
        owner: 'other',
        name: 'old-rec',
        description: '上期推荐',
        language: 'Go',
        stars: 100,
        score: 0.8,
        reason: null,
        url: 'https://github.com/other/old-rec',
        status: 'pushed',
        created_at: '2026-09-01 09:00:00',
      },
    ],
    trending: [
      {
        snapshot_date: '2026-10-20',
        repo_id: 'trend/one',
        owner: 'trend',
        name: 'one',
        html_url: 'https://github.com/trend/one',
        description: '热榜一',
        language: 'Rust',
        stars: 1000,
        star_delta: 300,
        rank: 3,
      },
      {
        snapshot_date: '2026-10-21',
        repo_id: 'trend/two',
        owner: 'trend',
        name: 'two',
        html_url: 'https://github.com/trend/two',
        description: '热榜二',
        language: 'Zig',
        stars: 2000,
        star_delta: 500,
        rank: 1,
      },
      {
        snapshot_date: '2026-09-01',
        repo_id: 'trend/old',
        owner: 'trend',
        name: 'old',
        html_url: 'https://github.com/trend/old',
        description: '上期热榜',
        language: 'C',
        stars: 500,
        star_delta: 900,
        rank: 1,
      },
    ],
    tags: [
      { repo_id: 'acme/new-repo', name: 'ai' },
      { repo_id: 'acme/old-repo', name: 'infra' },
    ],
  };
}

test('resolveReportPeriod：周报按周一到周日，current / previous 正确', () => {
  const current = resolveReportPeriod('weekly', NOW, 'current');
  assert.equal(current.start, '2026-10-19');
  assert.equal(current.end, '2026-10-22');
  assert.equal(current.title, '每周精选报告 · 10-19 ~ 10-22');

  const previous = resolveReportPeriod('weekly', NOW, 'previous');
  assert.equal(previous.start, '2026-10-12');
  assert.equal(previous.end, '2026-10-18');

  // 周日属于当周最后一天
  const sunday = resolveReportPeriod('weekly', new Date('2026-10-25T23:00:00Z'), 'current');
  assert.equal(sunday.start, '2026-10-19');
  assert.equal(sunday.end, '2026-10-25');
});

test('resolveReportPeriod：月报按自然月，跨年正确', () => {
  const current = resolveReportPeriod('monthly', NOW, 'current');
  assert.equal(current.start, '2026-10-01');
  assert.equal(current.end, '2026-10-22');
  assert.equal(current.title, '月度精选报告 · 2026 年 10 月');

  const previous = resolveReportPeriod('monthly', NOW, 'previous');
  assert.equal(previous.start, '2026-09-01');
  assert.equal(previous.end, '2026-09-30');

  const january = resolveReportPeriod('monthly', new Date('2026-01-15T00:00:00Z'), 'previous');
  assert.equal(january.start, '2025-12-01');
  assert.equal(january.end, '2025-12-31');
});

test('日期与统计辅助函数：非法日期、周期边界、千分位', () => {
  assert.equal(parseDateOnly('2026-02-30'), null);
  assert.equal(parseDateOnly('not-a-date'), null);
  assert.equal(isWithinPeriod('2026-10-19 00:00:00', { start: '2026-10-19', end: '2026-10-25' }), true);
  assert.equal(isWithinPeriod('2026-10-25 23:59:59', { start: '2026-10-19', end: '2026-10-25' }), true);
  assert.equal(isWithinPeriod('2026-10-26 00:00:00', { start: '2026-10-19', end: '2026-10-25' }), false);
  assert.equal(formatCount(1234567), '1,234,567');
  assert.equal(formatCount(0), '0');
});

test('buildReport：统计口径、分节排序与推荐过滤', () => {
  const period = resolveReportPeriod('weekly', NOW, 'current');
  const report = buildReport({
    userId: 'u1',
    kind: 'weekly',
    period,
    data: sampleData(),
    generatedAt: NOW,
  });

  assert.equal(report.status, 'ready');
  assert.equal(report.id, buildReportId('u1', 'weekly', '2026-10-19'));
  assert.equal(report.stats.totalRepos, 2);
  assert.equal(report.stats.newRepos, 1);
  assert.equal(report.stats.totalStars, 620);
  assert.equal(report.stats.newStars, 120);
  assert.equal(report.stats.categoryCount, 2);
  assert.equal(report.stats.languageCount, 2);
  assert.equal(report.stats.recommendationCount, 1);
  assert.equal(report.stats.trendingCount, 2);
  assert.equal(report.stats.topLanguage, 'Python');
  assert.equal(report.stats.topCategory, 'AI');

  const sections = Object.fromEntries(report.sections.map((section) => [section.key, section]));
  assert.equal(sections.new.items.length, 1);
  assert.equal(sections.new.items[0].id, 'acme/new-repo');
  assert.deepEqual(sections.new.items[0].tags, ['ai']);
  assert.equal(sections.new.items[0].category, 'AI');
  assert.equal(sections.top.items.length, 2);
  assert.equal(sections.top.items[0].id, 'acme/old-repo');
  assert.equal(sections.recommendations.items.length, 1);
  assert.equal(sections.recommendations.items[0].id, 'other/good-repo');
  assert.equal(sections.trending.items.length, 2);
  assert.equal(sections.trending.items[0].id, 'trend/two');

  assert.match(report.summary, /本周新增 1 个收藏/);
  assert.match(report.summary, /为你精选 1 个推荐/);
  assert.match(report.markdown, /^# 每周精选报告 · 10-19 ~ 10-22/);
  assert.match(report.markdown, /## 本期新增收藏/);
  assert.match(report.markdown, /\[acme\/new-repo\]\(https:\/\/github\.com\/acme\/new-repo\)/);
  assert.match(report.markdown, /推荐理由：与你收藏的 AI 项目相似/);
});

test('buildReport：新增统计按全量计算，分节只展示 Top 6', () => {
  const period = resolveReportPeriod('weekly', NOW, 'current');
  const repos = Array.from({ length: 8 }, (_, index) => ({
    id: `acme/r${index}`,
    name: `r${index}`,
    description: null,
    html_url: `https://github.com/acme/r${index}`,
    stars: index * 10,
    language: 'TypeScript',
    category_id: null,
    created_at: `${period.start} 10:00:00`,
    owner: 'acme',
  }));
  const report = buildReport({
    userId: 'u1',
    kind: 'weekly',
    period,
    data: { repos, categories: [], recommendations: [], trending: [], tags: [] },
    generatedAt: NOW,
  });

  assert.equal(report.stats.newRepos, 8);
  assert.equal(report.stats.newStars, 280);
  const newSection = report.sections.find((section) => section.key === 'new');
  assert.equal(newSection.items.length, 6);
});

test('buildReport：同一仓库重复推荐按最高分去重，热榜按最大涨幅去重', () => {
  const period = resolveReportPeriod('weekly', NOW, 'current');
  const baseRecommendation = {
    user_id: 'u1',
    owner: 'dup',
    name: 'repo',
    description: null,
    language: 'Go',
    stars: 100,
    reason: null,
    url: 'https://github.com/dup/repo',
    status: 'new',
    created_at: `${period.start} 09:00:00`,
  };
  const trendingBase = {
    repo_id: 'trend/same',
    owner: 'trend',
    name: 'same',
    html_url: 'https://github.com/trend/same',
    description: null,
    language: 'Rust',
    stars: 1000,
  };
  const report = buildReport({
    userId: 'u1',
    kind: 'weekly',
    period,
    data: {
      repos: [],
      categories: [],
      recommendations: [
        { ...baseRecommendation, id: 'rec-low', repo_id: 'dup/repo', score: 0.4 },
        { ...baseRecommendation, id: 'rec-high', repo_id: 'dup/repo', score: 0.9 },
      ],
      trending: [
        { ...trendingBase, snapshot_date: period.start, star_delta: 50, rank: 5 },
        { ...trendingBase, snapshot_date: period.end, star_delta: 300, rank: 1 },
      ],
      tags: [],
    },
    generatedAt: NOW,
  });

  assert.equal(report.stats.recommendationCount, 1);
  assert.equal(report.stats.trendingCount, 1);
  const sections = Object.fromEntries(report.sections.map((section) => [section.key, section]));
  assert.equal(sections.recommendations.items.length, 1);
  assert.equal(sections.recommendations.items[0].id, 'dup/repo');
  assert.equal(sections.trending.items.length, 1);
  assert.equal(sections.trending.items[0].starsDelta, 300);
});

test('buildReport：无数据时状态为 empty，摘要给出引导', () => {
  const period = resolveReportPeriod('monthly', NOW, 'current');
  const report = buildReport({
    userId: 'u2',
    kind: 'monthly',
    period,
    data: { repos: [], categories: [], recommendations: [], trending: [], tags: [] },
    generatedAt: NOW,
  });

  assert.equal(report.status, 'empty');
  assert.equal(report.stats.totalRepos, 0);
  assert.match(report.summary, /本月还没有可汇总的数据/);
  assert.match(report.markdown, /本周期暂无内容。/);
  assert.equal(report.sections.length, 4);
});

test('buildReportId：同一用户同一周期稳定，不同周期不同', () => {
  const a = buildReportId('u1', 'weekly', '2026-10-19');
  const b = buildReportId('u1', 'weekly', '2026-10-19');
  const c = buildReportId('u2', 'weekly', '2026-10-19');
  assert.equal(a, b);
  assert.notEqual(a, c);
  assert.match(a, /^rpt_weekly_20261019_[a-z0-9]+$/);
});
