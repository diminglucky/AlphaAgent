# Grafana / Prometheus integration

The platform emits metrics in Prometheus exposition format at:
```
GET /api/v1/metrics/prom
```

## Wire up

1. **Prometheus** — copy `prometheus.yml.example` to `/etc/prometheus/prometheus.yml`,
   replace `quant-host:8000` with your API host, restart Prometheus.

2. **Grafana** — Settings → Data Sources → Add Prometheus, point at your
   Prometheus URL.

3. **Import dashboard** — Dashboards → Import → upload `dashboard.json`,
   pick the Prometheus data source.

## What's in the dashboard

- 6 stat tiles: total/pending/filled/cancelled orders, blocked risk events, audit logs
- 2 timeseries: order rate + signal/recommendation rate
- 4 WS-subscriber stats
- KV cache hit rate gauge + per-function market-cache hit rate timeseries

## Adding panels

All metric names live in `apps/api/app/api/routes/metrics.py::get_metrics_prometheus`.
Append more gauges there, scrape Prometheus, and add a new panel referencing
the new metric name.

## Alert rule ideas (`alert_rules.yml`)

```yaml
groups:
  - name: quant-platform
    rules:
      - alert: QuantApiDown
        expr: up{job="quant-platform"} == 0
        for: 1m
        annotations:
          summary: Quant API down
      - alert: TooManyBlockedOrders
        expr: increase(quant_risk_events_blocked[10m]) > 20
        for: 5m
        annotations:
          summary: "Risk engine blocking >20 orders / 10min"
      - alert: AdvisorCacheStale
        expr: quant_advisor_cache_ready == 0
        for: 30m
        annotations:
          summary: Advisor pipeline has not produced a fresh report
```
