# 运维手册 (Runbook)

面向：运维 / 值班 / On-call。所有操作都假设你已经 `cd` 进入仓库根目录，并且
本地已激活 Python 环境（`source .venv/bin/activate` 或 conda env）。

> 设计文档对应章节：§9 部署 / §10 运维 / §10.4 开盘前检查 / §10.5 备份与恢复

---

## 1. 日常运维例行

### 1.1 开盘前 (T-15min ~ T-5min)
```bash
# 1) 后端如果不在跑就启动
uvicorn apps.api.app.main:app --host 0.0.0.0 --port 8000 &

# 2) 烟雾测试 — 8 项关键路径全部通过才允许开盘
python infra/scripts/smoke_test.py
# 退出码 0 = 全过；非 0 = 立即查看输出哪一项 FAIL，修复后再跑
```
关键检查项（节选）：
- `health` — API 存活
- `market_data` / `realtime_quote` — 行情通道可用
- `background_loops` — feed/advisor/scanner/monitor 循环全部 running
- `risk_rules` — 风控规则已加载
- `qmt_gateway` — 实盘网关（如果配了）

### 1.2 收盘后 (15:30 后)
```bash
# 备份数据库 + 运行时配置 + 近 7 日日志
bash infra/scripts/backup.sh
# 输出 → backups/quant_backup_<UTC>.tar.gz；自动保留最近 30 份

# (可选) 把日序列导入数据湖供研究使用
PYTHONPATH=. python infra/scripts/export_datalake.py --factors
```

### 1.3 cron 模板（参考）
```cron
# 每个交易日 09:00 执行开盘前自检（结果落日志）
0 9 * * 1-5  cd /path/to/repo && python infra/scripts/smoke_test.py --json >> logs/smoke.jsonl 2>&1

# 每个交易日 15:35 备份
35 15 * * 1-5  cd /path/to/repo && bash infra/scripts/backup.sh >> logs/backup.log 2>&1
```

---

## 2. 故障应对剧本

### 2.1 API 进程挂掉
1. `ps aux | grep uvicorn` 确认无残留
2. 检查 `logs/`（最近一两个文件）找异常栈
3. 重启：`uvicorn apps.api.app.main:app --host 0.0.0.0 --port 8000`
4. 跑 `python infra/scripts/smoke_test.py` 验证恢复

### 2.2 行情数据为空 / 卡死
症状：`/api/v1/market/quotes/realtime` 一直返回空。
- 大概率 `akshare` 网络问题。可临时改为 `mock` 数据源测试系统其余链路：
  ```bash
  export QUANT_MARKET_DATA_PROVIDER=mock
  ```
  再重启后端。
- 检查 `cache_stats` (`GET /api/v1/metrics`) 看命中率，如果 100% miss 说明上游全失败。

### 2.3 LLM 调用失败 / 超时
- 后端会自动降级到确定性 fallback 计划（不阻塞业务）。
- 在 `/api/v1/llm/config` 查看当前配置；通过 UI 的 LLM Settings 页一键测试。
- 如果是 key 问题，前端切换 provider 即可，无需重启。

### 2.4 实盘下单全部被风控拦截
- 查 `/api/v1/risk/events?limit=20`，按 `decision=BLOCK` 过滤。
- 如果是误判，在 UI 风控规则页临时禁用对应规则（admin 权限）。
- 必须留 audit log。

### 2.5 数据库损坏 / 误删（RTO < 30min）
```bash
# 1) 立刻停服，避免继续写入
pkill -f uvicorn

# 2) 找到最近的备份
ls -lh backups/

# 3) 恢复
bash infra/scripts/restore.sh backups/quant_backup_<最近>.tar.gz

# 4) 重启
uvicorn apps.api.app.main:app --host 0.0.0.0 --port 8000 &

# 5) 跑 smoke test 验收
python infra/scripts/smoke_test.py
```
> `restore.sh` 会自动把现有 `var/quant.db` 备份成 `quant.db.bak.<ts>` 后再覆盖。

---

## 3. 关键端点速查

| 用途 | 方法 | 路径 | 权限 |
|------|------|------|------|
| 健康检查 | GET | `/api/v1/health` | 公开 |
| 平台指标 | GET | `/api/v1/metrics` | 公开 |
| 后台循环状态 | GET | `/api/v1/ws/status` | 公开 |
| 实盘下单 | POST | `/api/v1/orders/live` | trader |
| 风控规则增删改 | POST/PATCH/DELETE | `/api/v1/risk/rules` | admin |
| LLM 配置变更 | POST/DELETE | `/api/v1/llm/config` | admin |
| Agent 触发 | POST | `/api/v1/agents/{scout,guardian,daily-brief}` | trader |
| 因子追溯 | GET | `/api/v1/research/factors/{symbol}` | 公开 |
| 模型运行历史 | GET | `/api/v1/research/runs` | 公开 |
| 审计日志 | GET | `/api/v1/admin/audit-logs` | admin |

---

## 4. 多 worker / 多机部署须知

如果用 `gunicorn -w >1`，必须配置 Redis 让缓存共享：
```bash
export QUANT_REDIS_URL=redis://your-host:6379/0
```
未配置时系统自动退回进程内存缓存（单 worker 也能用，多 worker 数据会割裂）。

---

## 5. 升级 / 迁移

1. 拉新代码：`git pull`
2. 安装依赖：`pip install -r requirements.txt`
3. 跑迁移：`alembic -c alembic.ini upgrade head`
4. 重启服务：`pkill -f uvicorn && uvicorn ... &`
5. smoke test 验收
6. 回归基线：`pytest tests/regression -q`（必须全过）

---

## 6. 监控与告警

最小可行监控（自带）：
- `/api/v1/metrics` — 各类计数 + 缓存命中率 + websocket 订阅数
- `/api/v1/ws/status` — 后台循环健康度

推荐外挂：
- Prometheus：抓 `/metrics`，告警阈值见 §10.3
- 日志聚合：`logs/*.log` → ELK / Loki
- 告警通道：webhook 已实现（`libs/notifications`），邮件可在 settings 配 SMTP
