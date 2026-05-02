# 部署指南

> 设计文档：§9 部署架构

## 1. 单机最小部署（开发 / 个人使用）

```bash
git clone <repo>
cd 量化交易
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 初始化 DB
alembic -c alembic.ini upgrade head

# 启动后端
uvicorn apps.api.app.main:app --host 0.0.0.0 --port 8000 &

# 启动前端 (Vue 3)
cd apps/web
npm install
npm run dev
# → http://localhost:5173
```

环境变量（最小集合）：

| 变量 | 默认 | 说明 |
|------|------|------|
| `QUANT_AUTH_ENABLED` | `false` | 生产必须为 `true` |
| `QUANT_API_KEYS` | — | `key1:admin,key2:trader` 形式 |
| `QUANT_DB_URL` | `sqlite:///var/quant.db` | 生产建议 PostgreSQL |
| `QUANT_MARKET_DATA_PROVIDER` | `akshare` | 离线/演示用 `mock` |
| `QUANT_LLM_PROVIDER` | `keyword` | `deepseek` / `openai` / `qwen` / `ollama` |
| `QUANT_LLM_API_KEY` | — | 对应 provider 的 key |
| `QUANT_REDIS_URL` | — | 多 worker 必填 |
| `QUANT_QMT_GATEWAY_URL` | — | 实盘网关 (见 [qmt-integration.md](qmt-integration.md)) |

---

## 2. 多 worker 生产部署

```bash
# Postgres
export QUANT_DB_URL="postgresql+psycopg://user:pass@db.host:5432/quant"
alembic -c alembic.ini upgrade head

# Redis（缓存 + 多 worker 一致性）
export QUANT_REDIS_URL="redis://redis.host:6379/0"

# 启动 4 worker
gunicorn apps.api.app.main:app \
    -k uvicorn.workers.UvicornWorker \
    -w 4 \
    -b 0.0.0.0:8000 \
    --timeout 60 \
    --access-logfile logs/access.log \
    --error-logfile  logs/error.log
```

前端构建：
```bash
cd apps/web
npm install && npm run build
# 把 dist/ 部署到 nginx / S3 / cdn 后面
```

---

## 3. Docker (推荐)

```dockerfile
# 仓库根目录已含 Dockerfile（最小镜像）
docker build -t quant-platform:latest .
docker run -d --name quant-api \
    -p 8000:8000 \
    -e QUANT_DB_URL=... \
    -e QUANT_LLM_API_KEY=... \
    -v $(pwd)/var:/app/var \
    -v $(pwd)/data:/app/data \
    -v $(pwd)/backups:/app/backups \
    quant-platform:latest
```

---

## 4. 启动后验证

```bash
python infra/scripts/smoke_test.py --base-url http://your-host:8000
# 8/8 PASS 才算上线成功
```

---

## 5. 监控接入

- Prometheus 抓 `/api/v1/metrics`（JSON 格式，需要 `json_exporter` 桥接，或自己加 Prom client）
- 日志：`logs/*.log` → ELK / Loki
- 告警：webhook 配在 `notification.providers.webhook_url`（admin 接口）

---

## 6. 升级流程

参见 [runbook.md §5](runbook.md#5-升级--迁移)。
