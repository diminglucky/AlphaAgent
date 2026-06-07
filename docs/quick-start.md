# 快速开始指南

## 环境要求

- Python 3.12+
- Node.js 18+ / npm
- SQLite（默认开发数据库）
- AKShare（已在项目依赖中，用于 A 股行情、K 线、新闻等数据）

## 安装

```bash
# 后端
pip install -e ".[dev]"

# 前端
cd apps/web
npm install
```

## 配置

复制 `.env.example` 为 `.env`，常用配置：

```bash
QUANT_DATABASE_URL=sqlite:///./var/quant.db
QUANT_AUTH_ENABLED=false  # 仅本地开发；代码默认开启认证
QUANT_LLM_PROVIDER=keyword
QUANT_FEISHU_WEBHOOK_URL=
```

生产部署时应设置：

```bash
QUANT_AUTH_ENABLED=true
QUANT_ADMIN_API_KEY=<strong-admin-key>
QUANT_TRADER_API_KEY=<strong-trader-key>
QUANT_VIEWER_API_KEY=<strong-viewer-key>
QUANT_CORS_ORIGINS=https://your-domain.example
```

LLM、飞书 Webhook、自动采样参数、固定验证时间、失败告警冷却和自动进化阈值可在网页「设置 / 模型进化」中运行时保存；运行时配置写入 `data/runtime_config.json`，不要提交到 git。自动采样默认关闭，开启后会定时运行 Scanner 生成待验证样本，LLM 终审默认仍关闭以控制成本。无人值守验证/采样失败可通过飞书告警，默认按失败类型冷却 3600 秒。

## 启动服务

```bash
# 后端 API
uvicorn apps.api.app.main:app --reload --port 8000 --env-file .env

# 前端开发服务
cd apps/web
npm run dev
```

访问：

- 前端开发地址：http://127.0.0.1:5173
- 后端 API 文档：http://127.0.0.1:8000/docs
- 前端生产挂载地址：http://127.0.0.1:8000/ui（先执行 `npm run build`）

## 运行测试

```bash
pytest -q
```

当前测试覆盖当前 AlphaAgent 轻量架构，包括 API、QMT gateway mock、Agent fallback、行情工具、提醒、数据库模型、研究/风控基础库和前端构建相关依赖。

## 当前 API 示例

### 健康检查

```bash
curl http://127.0.0.1:8000/api/v1/health
```

### 行情

```bash
curl "http://127.0.0.1:8000/api/v1/market/quote/600519.SH"
curl "http://127.0.0.1:8000/api/v1/market/quotes?symbols=600519.SH,000001.SZ"
curl "http://127.0.0.1:8000/api/v1/market/kline/600519.SH?period=daily&count=120"
curl "http://127.0.0.1:8000/api/v1/market/search?keyword=茅台"
curl "http://127.0.0.1:8000/api/v1/market/hot?top_n=50"
curl "http://127.0.0.1:8000/api/v1/market/cache-status"
```

### 自选股

```bash
curl http://127.0.0.1:8000/api/v1/watchlist/
curl -X POST http://127.0.0.1:8000/api/v1/watchlist/ \
  -H "Content-Type: application/json" \
  -d '{"symbol":"600519.SH","name":"贵州茅台"}'
curl http://127.0.0.1:8000/api/v1/watchlist/with-quotes
curl -X DELETE http://127.0.0.1:8000/api/v1/watchlist/600519.SH
```

### 持仓

```bash
curl http://127.0.0.1:8000/api/v1/positions/
curl -X POST http://127.0.0.1:8000/api/v1/positions/ \
  -H "Content-Type: application/json" \
  -d '{"symbol":"600519.SH","quantity":100,"avg_cost":1500,"stop_loss_pct":0.08,"take_profit_pct":0.2}'
curl -X DELETE http://127.0.0.1:8000/api/v1/positions/600519.SH
```

### 价格提醒

```bash
curl http://127.0.0.1:8000/api/v1/alerts/
curl -X POST http://127.0.0.1:8000/api/v1/alerts/ \
  -H "Content-Type: application/json" \
  -d '{"symbol":"600519.SH","name":"贵州茅台","alert_type":"price_above","target_price":1700}'
```

### Agent 和扫描器

```bash
curl -X POST http://127.0.0.1:8000/api/v1/agent/analyze/600519.SH
curl http://127.0.0.1:8000/api/v1/agent/cache
curl -X POST http://127.0.0.1:8000/api/v1/scanner/scan \
  -H "Content-Type: application/json" \
  -d '{"top_n":30,"min_score":50,"candidate_pool":120,"enable_llm":false}'
curl http://127.0.0.1:8000/api/v1/scanner/strategies
```

### LLM 配置

```bash
curl http://127.0.0.1:8000/api/v1/llm/config
curl -X POST http://127.0.0.1:8000/api/v1/llm/config \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: <admin-key-if-auth-enabled>" \
  -d '{"provider":"deepseek","model":"deepseek-chat","api_key":"sk-...","base_url":"https://api.deepseek.com/v1"}'
curl -X POST "http://127.0.0.1:8000/api/v1/llm/test?level=quick" \
  -H "X-Api-Key: <admin-key-if-auth-enabled>"
```

### 飞书通知

```bash
curl http://127.0.0.1:8000/api/v1/notify/status
curl -X POST http://127.0.0.1:8000/api/v1/notify/test \
  -H "Content-Type: application/json" \
  -d '{"title":"测试消息","content":"飞书机器人配置成功"}'
```

## QMT Gateway Mock

QMT gateway 是独立服务，默认 mock 后端可在任意系统运行：

```bash
QMT_BACKEND=mock python -m apps.qmt_gateway.main --port 8788
```

示例：

```bash
curl http://127.0.0.1:8788/health
curl -X POST http://127.0.0.1:8788/orders \
  -H "Content-Type: application/json" \
  -d '{"symbol":"600519.SH","side":"BUY","quantity":100,"order_type":"LIMIT","price":1500}'
```

## 数据库

启动时会自动创建当前核心表：

- `watchlist`
- `alerts`
- `positions`
- `analysis_cache`

SQLite 会启用 WAL、`synchronous=NORMAL` 和 `busy_timeout=5000`，适合本地单机和轻量部署。
