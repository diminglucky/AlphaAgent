# QMT 实盘对接指南

讯投 QMT 是 Windows-only 的本地交易终端（COM/Python API）。本平台
跑在 Linux/macOS 服务上，因此采用 **Gateway 模式**：

```
   ┌──────────────┐  HTTP  ┌──────────────┐  COM/xtquant  ┌──────────┐
   │  量化平台 API │ ─────► │ QMT Gateway   │ ────────────► │   QMT    │
   │ (Linux/Mac)   │ ◄───── │ (Windows服务) │               │ (本地)   │
   └──────────────┘        └──────────────┘               └──────────┘
```

> 设计文档：§5.5 实盘交易 / §9.1 部署架构 / §10.7 灾备

---

## 1. 准备

- Windows 10/11 + 已登录 QMT 客户端
- Python 3.10+ on Windows（独立于平台主进程）
- xtquant 包（QMT 安装目录自带）
- 可选：账户为模拟盘开始联调

---

## 2. 启动 Gateway（Windows 端）

仓库已实现一个最小可用的 stub gateway，供本地联调：
```
apps/qmt_gateway/
```
（Windows 才需要安装 xtquant 真实依赖；其他平台保持 stub 即可。）

```powershell
# 在 Windows 机器上
cd apps\qmt_gateway
pip install fastapi uvicorn xtquant     # xtquant 由 QMT 安装目录提供
python main.py --port 8788
# 默认监听 http://0.0.0.0:8788
```

健康检查：
```
GET http://<windows-host>:8788/health  →  {"status":"ok","backend":"xtquant"}
```

---

## 3. 配置量化平台

```bash
# 在跑 API 的机器上
export QUANT_QMT_GATEWAY_URL=http://<windows-host>:8788
export QUANT_QMT_API_KEY=...                   # 与 gateway 端配置一致
export QUANT_LIVE_TRADE_ENABLED=true           # 默认 false → 演练用
export QUANT_REQUIRE_MANUAL_CONFIRM=true       # 设计文档 §5.5.4 强约束
```

重启 API（或在 LLM Settings 之外的 admin 工具改 `.env` 后 reload）。

`smoke_test.py` 会自动检测 gateway 可达性。

---

## 4. 接口契约

QMT Gateway 必须实现以下端点（已在仓库 stub 中给出 schema）：

| 方法 | 路径 | 描述 |
|------|------|------|
| GET  | `/health` | 心跳 + 客户端登录状态 |
| POST | `/orders` | 下单（symbol/side/qty/price/order_type）|
| GET  | `/orders/{id}` | 单条订单查询 |
| POST | `/orders/{id}/cancel` | 撤单 |
| GET  | `/positions` | 当前持仓 |
| GET  | `/account` | 资金/可用 |

平台端使用 `apps/api/app/services/qmt_client.py` 调用 Gateway。

**风控始终在平台侧执行**——Gateway 无业务逻辑，只做协议翻译。

---

## 5. 联调步骤

1. 模拟盘登录 QMT，启动 Gateway
2. 平台设 `QUANT_LIVE_TRADE_ENABLED=false`，先用 `/api/v1/orders/live` 走完整链路
   （此时落 DB、走风控，但不发到 Gateway）
3. 设 `QUANT_LIVE_TRADE_ENABLED=true`，在前端 UI **手动确认** 一次单股小额下单
4. 在 QMT 客户端核对：成交回报 → DB `trade_fills` → 平台 `/portfolio/summary`
   三方一致
5. 接入告警通道（webhook / 邮件）
6. 全流程跑通后，才能切换到真盘

---

## 6. 故障与降级

| 现象 | 处理 |
|------|------|
| Gateway 不可达 | 平台返回 503；建议立即设 `QUANT_LIVE_TRADE_ENABLED=false`，转为下单暂存 |
| 报单超时但状态未知 | 不要重发！查 QMT 终端实际状态，再人工同步 DB 订单 |
| 行情/交易日历不一致 | 优先信任交易所日历（`trading_calendar` 表） |
| 风控全部 BLOCK | 查 `/risk/events`，必要时由 admin 在前端临时禁用规则（留 audit log）|

---

## 7. 安全

- Gateway 端口绝不要暴露公网；必须放在 VPN 或同一内网
- 平台 → Gateway 通信走 mTLS 或 API Key（`QUANT_QMT_API_KEY`）
- 资金账户密码不进入平台 DB；只在 QMT 客户端本地保管
