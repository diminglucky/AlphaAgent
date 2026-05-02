# A股智能量化交易平台

这是一个面向A股市场的智能量化交易平台，集成了数据获取、技术分析、风险管理、信号生成和推荐系统。

## 项目状态

- ✅ Phase 1: 项目骨架、基础API、数据模型
- ✅ Phase 2: 风险引擎、技术特征、信号引擎、数据管道
- 🚧 Phase 3: 新闻分析、LLM集成、组合优化
- 📋 Phase 4: 回测框架、QMT网关、Web界面

## 核心功能

### 已实现

1. **市场数据服务**
   - 股票列表查询
   - 历史K线数据（日线）
   - 实时行情快照
   - 多数据源支持（Mock/AKShare）
   - 自动回退机制

2. **投资组合管理**
   - 账户资产摘要
   - 持仓明细查询
   - 盈亏计算
   - 成本跟踪

3. **推荐系统**
   - 结构化买卖建议
   - 置信度评分
   - 风险标识
   - 推荐解释

4. **风险管理** ⭐ 新增
   - 单票权重限制
   - 行业集中度控制
   - 多规则验证
   - 风险决策引擎

5. **技术分析** ⭐ 新增
   - 技术指标计算（RSI、MA、波动率等）
   - 收益率分析
   - 成交量分析
   - 特征工程框架

6. **信号生成** ⭐ 新增
   - 多因子信号融合
   - 动量/趋势/成交量/波动率分析
   - 置信度评估
   - 推荐动作生成

7. **数据管道** ⭐ 新增
   - 历史数据批量回补
   - 增量数据更新
   - 进度跟踪
   - 错误处理

8. **订单模拟**
   - 风控检查
   - 资金校验
   - 仓位限制

## 快速开始

### 安装依赖

```bash
# 基础依赖
pip install -e .

# 开发依赖（包含测试）
pip install -e ".[dev]"

# 真实数据源（可选）
pip install -e ".[data]"
```

### 启动服务

```bash
# 使用Mock数据
uvicorn apps.api.app.main:app --reload

# 使用真实A股数据
export QUANT_MARKET_DATA_PROVIDER=akshare
uvicorn apps.api.app.main:app --reload

# 自动回退模式
export QUANT_MARKET_DATA_PROVIDER=auto
uvicorn apps.api.app.main:app --reload
```

访问：
- API服务：http://127.0.0.1:8000
- API文档：http://127.0.0.1:8000/docs

### 运行测试

```bash
# 运行所有测试（35个测试用例）
python3 -m pytest

# 查看详细输出
python3 -m pytest -v
```

## 技术栈

- **后端**: FastAPI + Python 3.9+
- **数据库**: SQLAlchemy 2.0 + SQLite（开发）/ PostgreSQL（生产）
- **数据源**: AKShare（免费A股数据）
- **测试**: pytest + httpx
- **迁移**: Alembic

## 测试覆盖

- 单元测试：27个
- 集成测试：8个
- 总计：35个测试用例
- 通过率：100%

## 文档

- [完整设计文档](docs/quant-trading-platform-design.md) - 架构设计、数据模型、API契约
- [Phase 2实现总结](docs/phase2-implementation.md) - 新增功能详解
- [快速开始指南](docs/quick-start.md) - 安装、配置、使用示例

## 使用示例

### Python SDK

```python
# 风险检查
from libs.risk.engine import RiskEngine

engine = RiskEngine()
result = engine.check_single_stock_weight(
    symbol="600519.SH",
    target_weight=0.25,
    current_weight=0.20,
)
print(f"通过: {result.passed}, 决策: {result.decision}")

# 技术分析
from libs.features.technical import build_technical_features

features = build_technical_features("600519.SH", bars)
print(f"RSI: {features.rsi_14d:.2f}")
print(f"5日收益率: {features.returns_5d:.2%}")

# 信号生成
from libs.recommendations.signal_engine import SignalEngine

engine = SignalEngine()
signal = engine.generate_signal(features)
action = engine.signal_to_action(signal)
print(f"信号: {signal.raw_score:.3f}, 动作: {action}")
```

### REST API

```bash
# 获取推荐
curl http://127.0.0.1:8000/api/v1/recommendations/latest

# 模拟下单
curl -X POST http://127.0.0.1:8000/api/v1/orders/simulate \
  -H "Content-Type: application/json" \
  -d '{"symbol":"600519.SH","side":"BUY","quantity":100,"price":1720.0}'
```

## 下一阶段

### Phase 3（进行中）
1. 新闻事件分析模块
2. LLM分析师集成
3. 组合优化算法
4. 市场状态判断

### Phase 4（规划中）
1. 回测框架集成
2. QMT/miniQMT网关
3. Web前端界面
4. 实盘交易对接

## 许可

MIT License
# liangHuaJiaoYi
