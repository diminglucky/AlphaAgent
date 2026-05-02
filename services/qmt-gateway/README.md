# QMT Gateway (Windows 节点)

该目录预留给 Windows 节点上的 `QMT/miniQMT` 物理部署。

实际实现位置（已完成）：

- **`apps/qmt_gateway/main.py`** — FastAPI Gateway 服务（HTTP→QMT 协议翻译）
- **`apps/qmt_gateway/backends.py`** — `MockBackend`（Linux/Mac 测试）+ `XtQuantBackend`（Windows 真实）
- **`apps/api/app/services/qmt_client.py`** — 主服务调用 Gateway 的客户端
- **`docs/qmt-integration.md`** — 完整集成指南

唯一剩余工作：在 Windows 物理机上安装 `xtquant`，填充 `XtQuantBackend.{place_order, cancel_order, list_positions, ...}` —
当前在非 Windows 环境抛 `NotImplementedError`，符合预期。
