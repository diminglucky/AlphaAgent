# QMT Gateway 说明

讯投 QMT 是 Windows-only 的本地交易终端（COM/Python API）。本平台
跑在 Linux/macOS 服务上，因此采用 **Gateway 模式**：

```
   ┌──────────────┐  HTTP  ┌──────────────┐  COM/xtquant  ┌──────────┐
   │  AlphaAgent   │ ─────► │ QMT Gateway   │ ────────────► │   QMT    │
   │ (Linux/Mac)   │ ◄───── │ (Windows服务) │               │ (本地)   │
   └──────────────┘        └──────────────┘               └──────────┘
```

> 当前状态：仓库已实现独立 QMT Gateway 和 mock backend；AlphaAgent 主 API 已接入 `/api/v1/trading/*` 转发下单/撤单，并提供 `/api/v1/trading/sync` 手动同步 Gateway 账户、持仓、订单和本地成交。

---

## 1. 准备

- Windows 10/11 + 已登录 QMT 客户端
- Python 3.10+ on Windows（独立于平台主进程）
- xtquant 包（QMT 安装目录自带）
- 可选：账户为模拟盘开始联调

---

## 2. 启动 Gateway（Windows 端）

仓库已实现一个最小可用的 gateway，供本地联调和 Windows 节点接入：
```
apps/qmt_gateway/
```
（Windows 才需要安装 xtquant 真实依赖；其他平台使用 mock backend。）

```powershell
# 在 Windows 机器上
cd apps\qmt_gateway
pip install fastapi uvicorn             # xtquant 通常由 QMT 安装目录提供
$env:QMT_BACKEND="xtquant"
$env:QMT_XT_USER_PATH="C:\...\userdata_mini"
$env:QMT_XT_ACCOUNT_ID="你的资金账号"
python main.py --port 8788
# 默认监听 http://0.0.0.0:8788
```

健康检查：
```
GET http://<windows-host>:8788/health  →  {"status":"ok","backend":"xtquant"}
```

---

## 3. 当前边界

- 可用：`apps/qmt_gateway/main.py` 提供独立 HTTP Gateway。
- 可用：`apps/qmt_gateway/backends.py` 提供跨平台 `MockBackend`，适合本地联调和测试。
- 可用：`XtQuantBackend` 已适配 xtquant 的下单、撤单、订单、持仓、资金查询，并统一映射为 Gateway DTO。
- 待验收：`XtQuantBackend` 需要在真实 Windows + QMT/miniQMT 机器上做模拟盘和小额实盘验收；非 Windows 环境不能验证 COM/本地终端行为。
- 已完成：AlphaAgent 主 API 可通过 `QUANT_TRADING_MODE=qmt` 转发 Gateway 下单/撤单。
- 已完成：AlphaAgent 主 API 可通过 `/trading/sync` 同步 Gateway `/orders`、`/positions`、`/account`，并按订单成交数量差额幂等生成 `trade_fills`。
- 已完成：QMT 模式的 `/trading/preview` 和 `/trading/orders` 使用本地已同步的 QMT 账户/持仓快照做资金、可卖数量、A 股规则和组合风控校验；未同步账户时直接拒绝，并返回 `requires_sync=true`。
- 配置：真实 backend 需要 `QMT_XT_USER_PATH`、`QMT_XT_ACCOUNT_ID`；可选 `QMT_XT_ACCOUNT_TYPE`、`QMT_XT_SESSION_ID`、`QMT_XT_STRATEGY_NAME`、`QMT_XT_MARKET_PRICE_TYPE_SH`、`QMT_XT_MARKET_PRICE_TYPE_SZ`。

---

## 4. 接口契约

QMT Gateway 必须实现以下端点（当前 mock backend 与 xtquant backend 共用同一 schema）：

| 方法 | 路径 | 描述 |
|------|------|------|
| GET  | `/health` | 心跳 + 客户端登录状态 |
| POST | `/orders` | 下单（symbol/side/qty/price/order_type）|
| GET  | `/orders/{id}` | 单条订单查询 |
| POST | `/orders/{id}/cancel` | 撤单 |
| GET  | `/positions` | 当前持仓 |
| GET  | `/account` | 资金/可用 |

Gateway 无业务逻辑，只做协议翻译。主 API 侧负责风控、人工确认和本地订单/成交/持仓对账。

---

## 5. Mock 联调步骤

1. 启动 mock gateway：`QMT_BACKEND=mock python -m apps.qmt_gateway.main --port 8788`
2. 调用 `GET /health` 确认 backend 为 `mock`
3. 调用 `POST /orders` 创建限价单
4. 调用 `POST /orders/{id}/simulate_fill` 模拟成交
5. 调用 `GET /positions` 和 `GET /account` 核对状态变化

---

## 6. 故障与降级

| 现象 | 处理 |
|------|------|
| Gateway 不可达 | 调用方应拒绝实盘动作，不能静默重试下单 |
| 预览/下单提示 requires_sync | 先调用 AlphaAgent `/api/v1/trading/sync` 同步 QMT 账户、持仓和订单 |
| 报单超时但状态未知 | 不要重发；查 QMT 终端实际状态，再人工同步 |
| xtquant 不可导入 | 非 Windows、未安装 QMT 依赖，或 Python 路径未包含 QMT 自带 xtquant |
| `QMT_XT_USER_PATH`/`QMT_XT_ACCOUNT_ID` 缺失 | 补齐 Windows 节点的 QMT 用户目录和资金账号 |
| 真实 backend 返回状态异常 | 先在模拟盘核对 QMT 终端订单、成交、资金和 Gateway `/orders`/`/account` 映射 |

---

## 7. 安全

- Gateway 端口绝不要暴露公网；必须放在 VPN 或同一内网
- 平台 → Gateway 通信走 mTLS 或 API Key（Gateway 端 `QMT_GATEWAY_API_KEY`，AlphaAgent 端 `QUANT_QMT_GATEWAY_API_KEY`）
- 资金账户密码不进入平台 DB；只在 QMT 客户端本地保管
