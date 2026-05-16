# 📈 A股智能助手

> LLM 驱动的 A 股实时行情 + 智能分析 + 飞书提醒一体化平台

一个简洁实用的 A 股投资辅助工具：实时看盘、AI 深度分析、价格提醒、持仓监控。所有 LLM 配置可在网页端动态修改，无需重启。

## ✨ 核心功能

| 功能 | 说明 |
|------|------|
| 📊 **实时行情** | 全市场 5000+ 只股票实时报价，3 秒刷新自选股，K 线 + 新闻一站式查看 |
| 🤖 **AI 智能分析** | 多技能并行 Agent，调用 7 个工具收集数据，LLM 综合输出决策仪表盘 |
| 🎯 **决策仪表盘** | 操作建议、4 档价格、仓位策略、检查清单、技术指标、情报中心一应俱全 |
| 🔔 **飞书实时提醒** | 价格突破/跌破、止损止盈、Agent 买入信号自动推送到飞书 |
| 📁 **自选股管理** | 搜索添加、实时行情、Agent 一键扫描全部 |
| 💼 **持仓跟踪** | 录入持仓、实时盈亏、自动监控止损止盈 |
| ⚙️ **配置热更新** | LLM API Key、模型、地址直接在网页配置，立即生效 |

## 🏗️ 架构

```
┌─────────────────────────────────────────────────────────────┐
│  前端 Vue3 + Element Plus + ECharts                         │
│  ├── 总览页（涨跌榜 + 自选股 + 详情抽屉）                    │
│  ├── 行情页（K线 + 量能 + 新闻 + 实时推送）                  │
│  ├── Agent 分析页（决策仪表盘）                              │
│  ├── 提醒页（价格触发 + 飞书状态）                           │
│  ├── 持仓页（实时盈亏 + 止损止盈）                           │
│  └── 设置页（LLM 配置热更新）                                │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  后端 FastAPI + SQLAlchemy + WebSocket                      │
│  ├── /market/*    行情/K线/新闻/搜索                         │
│  ├── /agent/*     SuperAnalyst 深度分析                      │
│  ├── /watchlist/* 自选股 CRUD                                │
│  ├── /alerts/*    价格提醒                                   │
│  ├── /positions/* 持仓管理                                   │
│  ├── /llm/*       LLM 配置热更新                             │
│  ├── /notify/*    飞书测试                                   │
│  └── /ws/*        WebSocket 实时推送                         │
└─────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
   ┌──────────┐       ┌──────────┐       ┌──────────┐
   │ AKShare  │       │ LLM API  │       │ 飞书机器人│
   │（行情）  │       │（分析）  │       │（推送）  │
   └──────────┘       └──────────┘       └──────────┘
```

## 🤖 SuperAnalystAgent 设计

参考 ReAct 但优化为**并行 + 单次综合**模式，比传统串行快 3-5 倍：

```
Phase 1（并行，ThreadPoolExecutor，~15s）
├── get_realtime_quote      实时报价
├── get_daily_bars(60)      60 日 K 线
├── get_technical_features  MA/RSI/MACD/KDJ/布林带
├── detect_chart_pattern    金叉/死叉/突破/背离
├── get_support_resistance  支撑/阻力位
├── search_news             近期新闻
└── analyze_news_sentiment  情绪评分

Phase 2（单次 LLM，~15s）
└── 综合所有数据 → 决策仪表盘 JSON
```

### 决策仪表盘输出

```json
{
  "action": "BUY|SELL|HOLD|WATCH",
  "confidence": 0-100,
  "current_price": 5.13,

  "core_conclusion": {
    "one_sentence": "一句话结论（直击要害）",
    "time_sensitivity": "时效性说明",
    "position_advice": {
      "no_position": "无持仓者具体建议",
      "has_position": "有持仓者具体建议"
    }
  },

  "battle_plan": {
    "ideal_buy": "理想买点 + 触发条件",
    "secondary_buy": "次要买点",
    "stop_loss": "止损价 + 触发条件",
    "take_profit": "止盈目标",
    "suggested_position": "建议仓位",
    "entry_plan": "建仓计划",
    "risk_control": "风控要点"
  },

  "action_checklist": ["执行前 5-8 项检查"],

  "data_perspective": {
    "trend_status": { "ma_alignment", "trend_score" },
    "price_position": { "ma5/10/20/60", "bias", "support", "resistance" },
    "volume_analysis": { "volume_ratio", "volume_meaning" },
    "rsi_status", "macd_status"
  },

  "intelligence": {
    "sentiment_summary": "市场情绪总结",
    "earnings_outlook": "业绩预期",
    "risk_alerts": ["风险点"],
    "positive_catalysts": ["利好"],
    "latest_news": "最新动态"
  }
}
```

### 七大交易军规（注入 system prompt）

1. 严进策略：乖离率 < 5% 才考虑入场
2. 趋势交易：MA5 > MA10 > MA20 多头排列才是好买点
3. 效率优先：必须有量能确认，无量上涨不可信
4. 买点偏好：优先回踩均线支撑的买点
5. 风险排查：重大利空一票否决
6. 量价配合：成交量验证价格运动
7. 强势股放宽：龙头股可适当放宽标准

## 🚀 快速开始

### 1. 安装依赖

```bash
git clone https://github.com/your-username/quant-assistant.git
cd quant-assistant

# 后端
pip install -e .

# 前端
cd apps/web && npm install
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入以下基础配置（LLM 可在网页端配置）
```

`.env` 主要配置：
```bash
QUANT_DATABASE_URL=sqlite:///./var/quant.db
QUANT_MARKET_DATA_PROVIDER=akshare
QUANT_QUOTE_INTERVAL=3       # WebSocket 推送间隔（秒）
QUANT_FEISHU_WEBHOOK_URL=    # 飞书机器人 webhook（可选）
```

### 3. 启动服务

```bash
# 后端（监听 8000 端口）
uvicorn apps.api.app.main:app --reload --port 8000 --env-file .env

# 前端开发模式（监听 5173）
cd apps/web && npm run dev

# 或构建生产前端，由后端统一服务
cd apps/web && npm run build
# 然后访问 http://localhost:8000/ui/
```

### 4. 配置 LLM（网页端）

打开 **设置页面**（`/settings`），快速选择预设：
- **DeepSeek**（推荐，性价比高）：`https://api.deepseek.com/v1` + `deepseek-chat`
- **OpenAI**：`https://api.openai.com/v1` + `gpt-4o-mini`
- **阿里云 Qwen**：`https://dashscope.aliyuncs.com/compatible-mode/v1` + `qwen-plus`
- **本地 Ollama**：`http://localhost:11434/v1` + `qwen2.5:7b`
- **Nbility 中转**：`https://api.nbility.dev/v1`

填入 API Key → 保存配置 → 测试连接，**立即生效，无需重启**。

### 5. 配置飞书机器人（可选）

1. 在飞书群设置 → 群机器人 → 添加机器人 → 自定义机器人
2. 复制 Webhook 地址
3. 填入 `.env`：`QUANT_FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx`
4. 重启服务后在设置页测试

## 📂 项目结构

```
量化交易/
├── apps/
│   ├── api/                # FastAPI 后端
│   │   └── app/
│   │       ├── api/routes/ # 7 个路由模块
│   │       ├── core/       # 配置 + 鉴权
│   │       ├── db/         # 4 张表（自选股/提醒/持仓/分析缓存）
│   │       └── services/   # 业务服务层
│   └── web/                # Vue3 前端
│       └── src/
│           ├── views/      # 6 个核心页面
│           ├── store.js    # 全局响应式状态 + WebSocket
│           └── api.js      # axios 接口封装
├── libs/                   # 共享库
│   ├── agents/             # SuperAnalystAgent + Skills
│   ├── llm_analyst/        # LLM 客户端 + 运行时配置
│   └── ...
├── data/                   # 运行时配置（gitignore）
└── var/                    # SQLite 数据库（gitignore）
```

## 🛠️ 技术栈

**后端**
- FastAPI + Uvicorn（异步 Web 框架）
- SQLAlchemy 2.0（ORM）
- SQLite（开发）/ PostgreSQL（生产）
- httpx（异步 HTTP 客户端）
- AKShare（A 股行情数据）
- WebSocket（实时推送）

**前端**
- Vue 3 + Vue Router
- Element Plus（UI 组件库）
- ECharts（K 线图）
- Vite（构建工具）
- 暗色主题

**LLM 集成**
- 兼容 OpenAI Chat Completions API
- 支持 DeepSeek / OpenAI / Qwen / Ollama / Nbility 等
- 运行时热更新配置（持久化到 `data/llm_runtime.json`）

## 📝 注意事项

- ⚠️ **不要把 `data/llm_runtime.json` 提交到 git**（包含 API Key），已加入 `.gitignore`
- ⚠️ **不要把 `.env` 提交到 git**，已在 `.gitignore`
- AKShare 部分接口偶尔会被远端断开，已加重试机制
- 行情数据有 30 秒缓存（全市场）和 3 秒精准刷新（自选股）两层
- 本项目仅供学习研究，**不构成任何投资建议**，股市有风险

## 📄 License

MIT
