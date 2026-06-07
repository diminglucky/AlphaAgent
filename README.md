# 🤖 AlphaAgent

> AI 驱动的 A 股潜力股发现 + 实时行情 + 智能分析 + 飞书提醒一体化平台

通过**三层漏斗 + LLM 终审**的架构，从全市场 5500+ 只股票中筛选明日真正可买入的标的，每只都有完整的「技术 + 基本面 + 资金面 + AI 立场」四维分析。

```
全市场 5500 只
   ↓ 一阶段过滤（ST/价格/涨跌幅/成交额）
候选池 ~3700 只
   ↓ Tier 1: 6 维度技术评分 + 11 种经典策略
技术海选 ~30 只
   ↓ Tier 2: 基本面 + 资金面（PE/市值/主力/龙虎榜）
基本面过滤 ~10-15 只
   ↓ Tier 3: SuperAnalystAgent (LLM 综合决策)
AI 推荐 ~5-8 只 + AI 否决列表（透明）
```

---

## ✨ 核心功能

| 功能 | 说明 |
|------|------|
| 🔥 **AI 潜力股扫描** | 三层漏斗筛选 + LLM 终审，每只输出 4 维独立分（技术/基本面/资金/AI） |
| 🤖 **Agent 单股分析** | 7 个工具并行 + LLM 综合，输出决策仪表盘（30s-2min/只） |
| 📊 **实时行情** | 全市场 5500+ 只 30s 刷新，自选股/持仓 3s 精准刷新 |
| 📉 **专业 K 线** | 日/周/月切换，MA5/MA20，今日实时 K 线高亮，三视图（K+量/纯K/纯量）切换 |
| 🎯 **明日交易计划** | 买入区间 / 止损 / 双目标（短/中线）/ 仓位 / 盈亏比 / 一句话操作 |
| 🔔 **飞书实时提醒** | 价格突破、止损止盈、AI BUY 信号自动推送（异步不阻塞） |
| 📁 **自选股 + 持仓** | 实时盈亏、止损止盈线，2 小时内不重复推送 |
| ⚙️ **LLM 配置热更新** | 网页改 API Key/模型/地址，立即生效，多 worker 自动同步 |

---

## 🏗️ 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│ Vue 3 + Element Plus + ECharts                              │
│  ├── 总览（涨跌榜 + 自选股 + 详情抽屉）                      │
│  ├── 行情（K线 + 新闻 + 实时推送）                           │
│  ├── 潜力扫描（三层漏斗 + 4 维评分卡 + AI 否决透明）         │
│  ├── Agent 分析（决策仪表盘 + 7 工具并行）                   │
│  ├── 提醒、持仓、设置                                         │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼ (REST + WebSocket)
┌─────────────────────────────────────────────────────────────┐
│ FastAPI + SQLAlchemy + asyncio                              │
│ ┌──────────────┬──────────────────────────────────────────┐ │
│ │ 路由 (10个)  │  /market /agent /scanner /watchlist /... │ │
│ ├──────────────┼──────────────────────────────────────────┤ │
│ │ 服务 (6个)   │ market / scanner / fundamental /         │ │
│ │              │ alert / feishu / llm                     │ │
│ ├──────────────┼──────────────────────────────────────────┤ │
│ │ 数据库       │ SQLite (WAL) — 自选股/提醒/持仓/AI缓存   │ │
│ ├──────────────┼──────────────────────────────────────────┤ │
│ │ 后台线程     │ 精准行情 (3s) + 全市场行情 (30s) +       │ │
│ │              │ WebSocket 推送 (3s)                      │ │
│ └──────────────┴──────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
        │                   │                   │
        ▼                   ▼                   ▼
  ┌──────────┐        ┌──────────┐        ┌──────────┐
  │ 数据源   │        │ LLM API  │        │ 飞书 Bot │
  │ ──────── │        │ ──────── │        │          │
  │ 新浪 hq  │        │ DeepSeek │        │ webhook  │
  │ 腾讯 K线 │        │ OpenAI   │        │          │
  │ 同花顺   │        │ Qwen     │        │          │
  │ 东财龙虎 │        │ Ollama   │        │          │
  └──────────┘        └──────────┘        └──────────┘
```

---

## 🚀 快速开始

### 1. 环境

- Python 3.12+
- Node.js 18+ / npm

### 2. 安装依赖

```bash
# 后端
pip install -e .

# 前端
cd apps/web
npm install
```

### 3. 配置

复制 `.env.example` 为 `.env`，关键项：

```bash
QUANT_DATABASE_URL=sqlite:///./var/quant.db
QUANT_AUTH_ENABLED=false      # 仅本地单机开发关闭；代码默认开启认证
QUANT_LLM_PROVIDER=deepseek    # 或 openai / qwen / ollama / keyword（不用 LLM）
# 飞书可选
QUANT_FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
```

LLM API Key 推荐**通过网页**配置（运行时持久化到 `data/llm_runtime.json`，文件权限 0600）。
飞书 Webhook、自动采样参数、固定验证时间、失败告警冷却和自动进化阈值也可在网页运行时保存，持久化到 `data/runtime_config.json`，文件权限 0600。后台自动采样默认关闭，开启后会定时运行 Scanner 并产生待验证预测样本；自动采样 LLM 默认关闭以控制成本。无人值守验证/采样失败可通过飞书告警，默认按失败类型冷却 3600 秒。

生产部署不要关闭认证；配置 `QUANT_ADMIN_API_KEY`、`QUANT_TRADER_API_KEY`、`QUANT_VIEWER_API_KEY`，并把 `QUANT_CORS_ORIGINS` 收敛到实际前端域名。

### 4. 启动

```bash
# 启动后端（自动启行情/WS 后台线程）
uvicorn apps.api.app.main:app --reload --port 8000 --env-file .env

# 启动前端（开发模式）
cd apps/web && npm run dev

# 或构建打包
cd apps/web && npm run build
# 然后 FastAPI 会自动挂载 dist/ 到 /ui
```

访问：
- 前端：`http://localhost:5173`（开发）或 `http://localhost:8000/ui`（生产）
- API 文档：`http://localhost:8000/docs`

### 5. 首次使用流程

1. 打开「设置」页填入 LLM API Key（DeepSeek 推荐，便宜稳定）
2. 在「自选股」搜索股票添加（也可在「行情」「总览」「扫描」页直接 +自选）
3. 在「潜力扫描」点开始扫描（首次约 3-5 分钟），获得 AI 推荐列表
4. 在「Agent 分析」深度分析感兴趣的股票
5. 在「持仓」录入持仓，自动监控止损止盈推送飞书

---

## 🔥 潜力股扫描详解

### 三层漏斗

| 层 | 输入 | 输出 | 耗时 | 工作 |
|---|---|---|---|---|
| **Tier 1** 技术海选 | 5500 只 | 30 只 | 1-2 min | 6 维度评分 + 11 种经典策略 |
| **Tier 2** 基本面 | 30 只 | 10-15 只 | 30-60s | PE/市值/资金流/龙虎榜 + 一票否决 |
| **Tier 3** AI 终审 | 12 只 | 5-8 只 | 1-3 min | LLM 综合决策（BUY/HOLD/WATCH/SELL） |

### Tier 1 — 6 维度技术评分（满分 100）

- **趋势 20 分**：均线排列、MA 金叉、价格位置
- **动量 15 分**：RSI、MACD（标准 9 日 EMA）、KDJ
- **量能 20 分**：放量、量价配合、量比
- **形态 15 分**：突破、回踩、底部反转
- **资金 15 分**：成交额连续放大、龙虎榜暗示
- **综合 15 分**：波动率、价格强度、健康位置

外加 11 种经典策略，每命中加 5 分（上限 +20）：放量上涨 / 均线多头 / 停机坪 / 回踩年线 / 突破平台 / 海龟交易 / 高而窄旗形 / 低 ATR 成长 / 四线多头 / 超跌反弹 / 双底突破

### Tier 2 — 基本面 + 资金面（独立两维各 25 分）

**一票否决**（命中即淘汰）：
- ST/*ST/退市风险
- 上市不满 60 天（次新股）
- 流通市值 < 30 亿（小盘庄股温床）
- PE < -100（严重亏损）或 PE > 200（估值严重过高）
- 龙虎榜跌幅净卖出

**基本面分（0-25）**：
- PE 估值 10 分（≤20 满分，60-100 倒扣）
- 流通市值 10 分（50-300 亿满分，>1000 亿减分）
- PB 估值 5 分

**资金面分（0-25）**：
- 当日主力净流入 12 分
- 换手率 5 分（3-10% 健康）
- 龙虎榜机构净买入 8 分

### Tier 3 — LLM 终审

每只股票调用 `SuperAnalystAgent`，但**复用 Tier-1+Tier-2 已经算好的所有数据**（不重复拉 K 线/新闻），让 LLM 看到与扫描器一致的指标 + 基本面 + 资金面 + 行业景气度，给出：
- BUY / HOLD / WATCH / SELL
- 置信度 0-100
- 一句话结论 + 持仓/无持仓双栏建议
- 看好理由 + 风险提示 + 催化剂

只有 `BUY` 或 `HOLD` 且 `confidence ≥ 55` 的进入推荐列表，其余进入「AI 否决」折叠区域（透明展示原因）。

### 排序

```
Tier 优先：BUY > HOLD > 其他
同档按 综合可信度 = 技术×0.4 + 基本面×1.2 + 资金面×1.2 + AI 置信度×0.4
```

### LLM 失败兜底

如果 LLM 调用失败（402 余额不足 / 超时 / 限流），自动 fallback 到规则引擎，前端显示红色 banner 提示并用 ⚙️ 图标标记规则引擎结果（区别于真 LLM 的 🤖）。

---

## 🤖 Agent 单股分析

`SuperAnalystAgent` 并行调用 7 个工具收集数据，再交给 LLM 综合：

```
┌─ 并行 (ThreadPoolExecutor, 7 workers, 30s/工具) ──┐
│  • get_realtime_quote     实时报价                │
│  • get_daily_bars         60 日 K 线              │
│  • get_technical_features 技术指标               │
│  • detect_chart_pattern   K 线形态               │
│  • get_support_resistance 支撑/阻力              │
│  • search_news            7 天新闻               │
│  • analyze_news_sentiment 新闻情绪               │
└──────────────────────────────────────────────────┘
                        ↓
              LLM 综合（4-8K tokens）
                        ↓
   决策仪表盘 JSON（含 core_conclusion / battle_plan / ...）
```

输出结构：
- `core_conclusion`：一句话 + 时效性 + 持仓/无持仓建议
- `battle_plan`：理想买点 / 次要买点 / 止损 / 止盈 / 仓位
- `action_checklist`：执行前检查清单 5-8 项
- `data_perspective`：均线/价格位置/量能/RSI/MACD 解读
- `intelligence`：情绪/业绩/利好/风险/最新消息

LLM 失败时降级为 7 维信号规则引擎（趋势/均线/RSI/MACD/量比/形态/情绪），仍能给出 BUY/SELL/HOLD/WATCH 决策。

---

## 🔔 飞书提醒

价格提醒、AI BUY 信号、持仓止损止盈触发自动推送（**异步 fire-and-forget，不阻塞主流程**）。

去重逻辑：
- 价格提醒：触发后标记 `triggered=True`，不再重复
- 持仓止损/止盈：双层冷却（内存 2 小时 + DB `last_alert_at` 持久化），重启不重发

未配置飞书时，提醒仍记录到数据库，前端「提醒」页面可见。

---

## 📊 数据源

| 数据 | 来源 | 备注 |
|------|------|------|
| 实时行情（精准） | 新浪 `hq.sinajs.cn` | 自选股+持仓，3s 刷新 |
| 全市场行情 | AKShare `stock_zh_a_spot` (新浪) | 30s 刷新 |
| K 线 | AKShare `stock_zh_a_hist_tx` (腾讯) | 日/周/月，含今日实时 K 线 |
| PE/PB/市值 | AKShare `stock_value_em` (东方财富) | 6 小时缓存 |
| 资金流 | AKShare `stock_fund_flow_individual` (同花顺) | 1 小时缓存全市场 |
| 行业 | AKShare `stock_fund_flow_industry/concept` | 30 分钟缓存 |
| 龙虎榜 | AKShare `stock_lhb_detail_em` | 24 小时缓存（不可达时优雅降级） |
| 新闻 | AKShare `stock_news_em` | 按需拉取 |

涨跌停按板块自动识别：
- 北交所 30%
- 创业板/科创板 20%
- 主板 10%
- ST 5%

---

## 🏗️ 目录结构

```
AlphaAgent/
├── apps/
│   ├── api/                       # FastAPI 后端
│   │   └── app/
│   │       ├── api/routes/        # 10 个路由（health/market/agent/scanner/...）
│   │       ├── core/              # 配置 + 认证
│   │       ├── db/                # SQLAlchemy 模型 + WAL 配置
│   │       ├── services/          # 6 个核心服务
│   │       │   ├── market_service.py       # 行情双层缓存
│   │       │   ├── scanner_service.py      # 三层漏斗扫描
│   │       │   ├── fundamental_service.py  # 基本面+资金面+行业
│   │       │   ├── alert_service.py        # 提醒触发+去重
│   │       │   ├── feishu_service.py       # 异步飞书推送
│   │       │   └── llm_service.py
│   │       └── main.py
│   └── web/                       # Vue 3 前端
│       └── src/
│           ├── views/             # 7 个页面
│           ├── api.js, store.js, router/
│           └── App.vue            # keep-alive 缓存所有页面
├── libs/
│   ├── agents/                    # SuperAnalystAgent + 工具集
│   ├── llm_analyst/               # LLM 客户端 + 运行时配置（mtime 自动重载）
│   └── ...                        # 其他 lib（部分 legacy，未在 router 中）
├── data/                          # 运行时数据（不入 git）
│   ├── llm_runtime.json           # LLM 配置（chmod 600）
│   └── quant.db                   # SQLite + WAL
└── .env / .env.example
```

---

## 🧪 关键 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/market/quote/{symbol}` | GET | 单股实时行情 |
| `/api/v1/market/kline/{symbol}` | GET | K 线（period=daily/weekly/monthly） |
| `/api/v1/market/search` | GET | 股票搜索 |
| `/api/v1/agent/analyze/{symbol}` | POST | SuperAnalystAgent 单股分析 |
| `/api/v1/scanner/scan` | POST | 三层漏斗扫描（body 含全部参数） |
| `/api/v1/scanner/strategies` | GET | 11 种经典策略元信息 |
| `/api/v1/llm/config` | GET/POST/DELETE | LLM 配置查询/更新/重置 |
| `/api/v1/llm/test` | POST | 验证 LLM 配置（quick/standard/full） |
| `/api/v1/watchlist/with-quotes` | GET | 自选股 + 实时行情 |
| `/api/v1/positions/` | GET/POST/DELETE | 持仓管理（自动清相关提醒） |
| `/api/v1/ws/quotes` | WebSocket | 行情推送（3s） |
| `/api/v1/ws/alerts` | WebSocket | 提醒推送（实时） |

---

## ⚠️ 已知限制

1. **东方财富某些接口不稳定**：`stock_individual_info_em` / `stock_individual_fund_flow` 容易 `Connection aborted`。已切换到稳定的 `stock_value_em` (PE/PB/市值) 和 `stock_fund_flow_individual` (同花顺)，部分仍依赖东财的接口（如龙虎榜）失败时优雅降级。
2. **LLM 余额管理**：DeepSeek/OpenAI 用完会返回 402，扫描器会 fallback 到规则引擎，前端会显示告警 banner 提示充值。
3. **三层扫描时间**：完整扫描约 3-5 分钟，受 LLM 速度影响较大。结果缓存 5 分钟。
4. **akshare 数据延迟**：盘中实时行情依赖新浪/腾讯，秒级；基本面/资金流/龙虎榜数据通常盘后更新。
5. **历史数据迁移**：DB 自动 ALTER TABLE 兼容旧表（`positions.last_alert_at` / `analysis_cache.updated_at`）。

---

## 📜 License

仅供个人学习/研究使用，**不构成投资建议**。所有买卖决策由用户自行承担。

---

## 📞 交接说明

详见 [HANDOVER.md](HANDOVER.md)，包含：
- 完整文件清单 + 每个文件的作用
- 所有已知 bug 修复 + 设计决策
- 每个核心服务的工作机制
- 故障排查手册
- 后续优化方向
