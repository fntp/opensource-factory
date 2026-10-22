import assert from 'node:assert/strict';
import test from 'node:test';

import {
  combineStatus,
  metricDate,
  normalizeRoute,
  parseMetricDays,
  shouldRecordMetric,
  statusClass,
  summarizeMetricRows,
} from '../src/monitoring/metrics.ts';

const NOW = new Date('2026-10-22T08:00:00Z');

test('metricDate 使用 UTC 日期', () => {
  assert.equal(metricDate(NOW), '2026-10-22');
});

test('parseMetricDays 默认 7，范围 1~30', () => {
  assert.equal(parseMetricDays(undefined), 7);
  assert.equal(parseMetricDays(''), 7);
  assert.equal(parseMetricDays('0'), 1);
  assert.equal(parseMetricDays('-5'), 1);
  assert.equal(parseMetricDays('14'), 14);
  assert.equal(parseMetricDays('99'), 30);
});

test('statusClass 按状态码分段', () => {
  assert.equal(statusClass(200), '2xx');
  assert.equal(statusClass(302), '3xx');
  assert.equal(statusClass(404), '4xx');
  assert.equal(statusClass(503), '5xx');
  assert.equal(statusClass(101), '1xx');
});

test('normalizeRoute 折叠数字 / UUID / 长十六进制 ID', () => {
  assert.equal(normalizeRoute('/api/repos/123/detail'), '/api/repos/:id/detail');
  assert.equal(
    normalizeRoute('/api/trending/550e8400-e29b-41d4-a716-446655440000'),
    '/api/trending/:id'
  );
  assert.equal(normalizeRoute('/api/repos/owner/name?x=1'), '/api/repos/owner/name');
  assert.equal(normalizeRoute('/healthz'), '/healthz');
  assert.equal(normalizeRoute(''), '/');
});

test('shouldRecordMetric 跳过预检与内部接口', () => {
  assert.equal(shouldRecordMetric('GET', '/api/repos'), true);
  assert.equal(shouldRecordMetric('POST', '/api/monitoring/check'), true);
  assert.equal(shouldRecordMetric('OPTIONS', '/api/repos'), false);
  assert.equal(shouldRecordMetric('GET', '/api/internal/analytics'), false);
  assert.equal(shouldRecordMetric('GET', '/healthz'), false);
});

test('summarizeMetricRows 汇总总量 / 每日 / 路由并计算错误率与均值', () => {
  const rows = [
    {
      metric_date: '2026-10-21',
      route: '/api/repos',
      method: 'GET',
      status_class: '2xx',
      requests: 8,
      total_ms: 400,
      max_ms: 120,
    },
    {
      metric_date: '2026-10-21',
      route: '/api/repos',
      method: 'GET',
      status_class: '5xx',
      requests: 2,
      total_ms: 300,
      max_ms: 200,
    },
    {
      metric_date: '2026-10-22',
      route: '/api/trending',
      method: 'GET',
      status_class: '4xx',
      requests: 1,
      total_ms: 50,
      max_ms: 50,
    },
  ];

  const summary = summarizeMetricRows(rows, 2, NOW);
  assert.equal(summary.days, 2);
  assert.equal(summary.from, '2026-10-21');
  assert.equal(summary.to, '2026-10-22');
  assert.equal(summary.totals.requests, 11);
  assert.equal(summary.totals.errors, 3);
  assert.equal(summary.totals.serverErrors, 2);
  assert.equal(summary.totals.errorRate, 27.3);
  assert.equal(summary.totals.avgMs, 68.2);
  assert.equal(summary.totals.maxMs, 200);

  assert.equal(summary.daily.length, 2);
  assert.equal(summary.daily[0].date, '2026-10-21');
  assert.equal(summary.daily[0].requests, 10);
  assert.equal(summary.daily[1].requests, 1);

  assert.equal(summary.routes[0].route, '/api/repos');
  assert.equal(summary.routes[0].requests, 10);
  assert.equal(summary.routes[0].errorRate, 20);
});

test('combineStatus 优先 VPS，其次 Workers 错误率', () => {
  assert.equal(combineStatus('critical', null), 'critical');
  assert.equal(combineStatus('warning', null), 'warning');
  assert.equal(combineStatus('ok', null), 'ok');
  assert.equal(combineStatus(undefined, null), 'unknown');
  assert.equal(
    combineStatus(undefined, {
      days: 7,
      from: '2026-10-16',
      to: '2026-10-22',
      totals: { requests: 100, errors: 15, serverErrors: 0, errorRate: 15, avgMs: 1, maxMs: 1 },
      daily: [],
      routes: [],
    }),
    'warning'
  );
});
