# QMT Gateway (Windows 节点)

该目录预留给 Windows 节点上的 `QMT/miniQMT` 物理部署。

实际实现位置：

- **`apps/qmt_gateway/main.py`** — FastAPI Gateway 服务（HTTP→QMT 协议翻译）
- **`apps/qmt_gateway/backends.py`** — `MockBackend`（Linux/Mac 测试）+ `XtQuantBackend`（Windows/xtquant 真实适配层）
- **`docs/qmt-integration.md`** — 当前 Gateway 边界说明

当前边界：

- `MockBackend` 可用于本地联调和测试。
- `XtQuantBackend` 已实现 `order_stock`、撤单、订单、持仓、资金查询的适配与 DTO 映射；上线前仍必须在 Windows + QMT/miniQMT 实机环境完成验收。
- AlphaAgent 主 API 已通过 `/api/v1/trading/*` 支持转发 Gateway 下单/撤单，并通过 `/api/v1/trading/sync` 手动同步 Gateway 账户、持仓、订单和本地成交。
