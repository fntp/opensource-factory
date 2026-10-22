-- Workers 请求指标（REQ-202610-0941 / M5-03）
-- 按 (日期, 路由, 方法, 状态类) 聚合，避免逐请求存储导致 D1 膨胀。
CREATE TABLE IF NOT EXISTS worker_metrics (
  metric_date TEXT NOT NULL,
  route TEXT NOT NULL,
  method TEXT NOT NULL,
  status_class TEXT NOT NULL,
  requests INTEGER NOT NULL DEFAULT 0,
  total_ms INTEGER NOT NULL DEFAULT 0,
  max_ms INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (metric_date, route, method, status_class)
);

CREATE INDEX IF NOT EXISTS idx_worker_metrics_date ON worker_metrics (metric_date);
