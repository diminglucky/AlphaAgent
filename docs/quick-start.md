# 快速开始指南

## 环境要求

- Python 3.9+
- SQLite（开发环境）
- 可选：AKShare（真实A股数据）

## 安装

### 1. 安装基础依赖

```bash
pip install -e .
```

### 2. 安装开发依赖（可选）

```bash
pip install -e ".[dev]"
```

### 3. 安装数据源（可选）

```bash
pip install -e ".[data]"
```

## 启动服务

### 使用Mock数据（默认）

```bash
uvicorn apps.api.app.main:app --reload
```

访问：http://127.0.0.1:8000

API文档：http://127.0.0.1:8000/docs

### 使用真实A股数据

```bash
export QUANT_MARKET_DATA_PROVIDER=akshare
uvicorn apps.api.app.main:app --reload
```

### 自动回退模式

```bash
export QUANT_MARKET_DATA_PROVIDER=auto
uvicorn apps.api.app.main:app --reload
```

## 运行测试

```bash
# 运行所有测试
python3 -m pytest

# 运行单元测试
python3 -m pytest tests/unit/ -v

# 运行集成测试
python3 -m pytest tests/integration/ -v

# 查看测试覆盖率
python3 -m pytest --cov=apps --cov=libs
```

## API使用示例

### 1. 健康检查

```bash
curl http://127.0.0.1:8000/api/v1/health
```

### 2. 查看数据源状态

```bash
curl http://127.0.0.1:8000/api/v1/market/provider/status
```

### 3. 获取股票列表

```bash
curl http://127.0.0.1:8000/api/v1/market/instruments
```

### 4. 获取历史K线

```bash
curl "http://127.0.0.1:8000/api/v1/market/bars?symbol=600519.SH&freq=1d&start=2026-04-01&end=2026-04-25"
```

### 5. 获取实时行情

```bash
curl "http://127.0.0.1:8000/api/v1/market/quotes/realtime?symbols=600519.SH,000001.SZ"
```

### 6. 查看投资组合

```bash
curl http://127.0.0.1:8000/api/v1/portfolio/summary
curl http://127.0.0.1:8000/api/v1/portfolio/positions
```

### 7. 获取推荐建议

```bash
curl http://127.0.0.1:8000/api/v1/recommendations/latest
```

### 8. 获取推荐解释

```bash
curl -X POST http://127.0.0.1:8000/api/v1/recommendations/explain \
  -H "Content-Type: application/json" \
  -d '{"symbol": "600519.SH"}'
```

### 9. 模拟下单

```bash
curl -X POST http://127.0.0.1:8000/api/v1/orders/simulate \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "600519.SH",
    "side": "BUY",
    "quantity": 100,
    "price": 1720.0
  }'
```

## Python SDK使用示例

### 风险检查

```python
from libs.risk.engine import RiskEngine

engine = RiskEngine()

# 检查单票权重
result = engine.check_single_stock_weight(
    symbol="600519.SH",
    target_weight=0.25,
    current_weight=0.20,
)

print(f"通过: {result.passed}")
print(f"决策: {result.decision}")
print(f"消息: {result.message}")
```

### 技术分析

```python
from datetime import date
from libs.features.technical import build_technical_features

# 准备K线数据
bars = [
    (date(2026, 4, 1), 1700.0, 30000, 0.5),
    (date(2026, 4, 2), 1710.0, 32000, 0.6),
    (date(2026, 4, 3), 1720.0, 35000, 0.7),
    # ... 更多数据
]

# 计算技术特征
features = build_technical_features("600519.SH", bars)

print(f"当前价格: {features.close}")
print(f"5日收益率: {features.returns_5d:.2%}")
print(f"RSI(14): {features.rsi_14d:.2f}")
print(f"MA(5): {features.ma_5d:.2f}")
```

### 信号生成

```python
from libs.recommendations.signal_engine import SignalEngine

engine = SignalEngine()

# 从技术特征生成信号
signal = engine.generate_signal(features)

print(f"信号得分: {signal.raw_score:.3f}")
print(f"置信度: {signal.confidence:.2%}")

# 转换为推荐动作
action = engine.signal_to_action(signal)
print(f"推荐动作: {action}")

# 查看各组件得分
for component, score in signal.components.items():
    print(f"{component}: {score:.3f}")
```

### 数据回补

```python
from datetime import date
from pipelines.backfill.daily_bars import DailyBarBackfillPipeline
from apps.api.app.services.market_service import MarketService

# 使用市场服务的数据提供者
service = MarketService()
pipeline = DailyBarBackfillPipeline(service.provider)

# 回补单个股票
bars = pipeline.backfill_symbol(
    symbol="600519.SH",
    start_date=date(2026, 1, 1),
    end_date=date(2026, 4, 25),
)

print(f"获取到 {len(bars)} 条K线数据")

# 增量更新
results = pipeline.incremental_update(
    symbols=["600519.SH", "000001.SZ", "300750.SZ"],
    lookback_days=5,
)

for symbol, bars in results.items():
    print(f"{symbol}: {len(bars)} 条数据")
```

## 配置说明

### 环境变量

```bash
# 应用配置
export QUANT_APP_NAME="A股智能量化交易平台"
export QUANT_APP_ENV="dev"
export QUANT_API_V1_PREFIX="/api/v1"

# 数据源配置
export QUANT_MARKET_DATA_PROVIDER="mock"  # mock | akshare | auto
export QUANT_DEFAULT_CURRENCY="CNY"

# 交易模式
export QUANT_SIMULATED_TRADING="true"

# 数据库配置
export QUANT_DATABASE_URL="sqlite:///./var/quant.db"
export QUANT_DATABASE_ECHO="false"

# 演示数据
export QUANT_SEED_DEMO_DATA="true"
```

### 数据库初始化

首次启动时会自动：
1. 创建数据库表结构
2. 填充演示数据（如果`QUANT_SEED_DEMO_DATA=true`）

手动重置数据库：

```bash
rm var/quant.db
uvicorn apps.api.app.main:app --reload
```

## 常见问题

### Q: 如何切换到真实数据源？

A: 安装akshare并设置环境变量：

```bash
pip install akshare
export QUANT_MARKET_DATA_PROVIDER=akshare
```

### Q: 真实数据源失败怎么办？

A: 使用auto模式自动回退：

```bash
export QUANT_MARKET_DATA_PROVIDER=auto
```

### Q: 如何禁用演示数据？

A: 设置环境变量：

```bash
export QUANT_SEED_DEMO_DATA=false
```

### Q: 测试失败怎么办？

A: 确保Python版本>=3.9，并安装所有依赖：

```bash
python3 --version
pip install -e ".[dev]"
python3 -m pytest -v
```

### Q: 如何查看详细日志？

A: 启动时添加日志级别：

```bash
export LOG_LEVEL=DEBUG
uvicorn apps.api.app.main:app --reload --log-level debug
```

## 下一步

- 查看[设计文档](quant-trading-platform-design.md)了解完整架构
- 查看[Phase 2实现](phase2-implementation.md)了解新增功能
- 访问API文档：http://127.0.0.1:8000/docs
- 开始开发自定义策略和指标
