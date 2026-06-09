# 📋 项目交接文档

> 项目：AlphaAgent (A股智能助手)  
> 仓库：`git@github.com:diminglucky/AlphaAgent.git`  
> 当前 HEAD：以 `git log -1 --oneline` 为准

本文档记录项目结构、设计决策、已修复问题、运维注意事项和后续路线。新接手的开发者读完这份文档应该能在 30 分钟内上手。

---

## 一、项目背景

### 1.1 起源
项目最初是一个复杂的量化交易框架（19 张表 + 18 个服务），后**精简重构**为聚焦个人投资辅助的轻量平台，核心定位：

> 让一个普通散户能从全市场 5500 只股票里，每天找到 5-8 只**真正可买入**的潜力股，并配套买入区间/止损/目标价/仓位计划。

### 1.2 核心矛盾解决
之前的版本存在最大的设计矛盾：**「潜力扫描」给某只股票推荐 BUY，但点进 Agent 单股分析却给 SELL/WATCH**——因为两者用的是完全独立、不通气的判断逻辑。

**当前版本通过三层漏斗 + LLM 数据复用解决**：扫描器 Tier-3 阶段把 Tier-1 的技术指标和 Tier-2 的基本面数据**全部传给** SuperAnalystAgent（同 Agent 单股分析的引擎），LLM 看到与扫描器一致的数据，因此结论一致。

---

## 二、当前架构

### 2.1 技术栈

| 层 | 技术 |
|---|---|
| 后端 | FastAPI 0.110+ / Python 3.12 / SQLAlchemy 2.0 / SQLite (WAL) |
| 前端 | Vue 3 / Vite / Element Plus / ECharts / vue-router (hash mode) |
| 数据 | AKShare（新浪 + 腾讯 + 东方财富 + 同花顺多源） |
| LLM | LLMClient 适配 OpenAI 兼容协议（DeepSeek / OpenAI / Qwen / Ollama） |
| 推送 | 飞书 Webhook（异步 ThreadPoolExecutor fire-and-forget） |
| 通信 | REST + WebSocket（行情 / 提醒） |

### 2.2 服务模块（8 个核心服务，已删 22 个 dead service）

| 服务 | 文件 | 职责 |
|---|---|---|
| market | `market_service.py` | 行情双层缓存（精准 3s + 全市场 30s）、K 线、新闻、搜索 |
| scanner | `scanner_service.py` | 三层漏斗扫描，6 维度技术评分 + 11 种策略 + LLM 终审 |
| fundamental | `fundamental_service.py` | PE/PB/市值/资金流/龙虎榜/行业景气度/北向持股变化/机构研报评级/减持风险 |
| alert | `alert_service.py` | 价格提醒 + 持仓止损止盈，去重 + 异步飞书 |
| feishu | `feishu_service.py` | 飞书卡片推送（线程池异步） |
| llm | `llm_service.py` | LLM 客户端封装 |
| evolution | `evolution_service.py` | 扫描结果落库、预测到期验证、模型权重校准与版本进化 |
| trading | `trading_service.py` | 模拟盘/QMT Gateway 统一下单、成交和账户；模拟盘持仓与手动持仓隔离 |

### 2.3 路由（12 个，全部生产用）

```python
# apps/api/app/api/router.py
api_router.include_router(health.router)       # GET /health
api_router.include_router(market.router)        # /market/*
api_router.include_router(watchlist.router)     # /watchlist/*
api_router.include_router(agent.router)         # /agent/*
api_router.include_router(alerts.router)        # /alerts/*
api_router.include_router(positions.router)     # /positions/*
api_router.include_router(notify.router)        # /notify/*  (飞书测试)
api_router.include_router(llm_config.router)    # /llm/*
api_router.include_router(scanner.router)       # /scanner/*
api_router.include_router(evolution.router)     # /evolution/*
api_router.include_router(trading.router)       # /trading/*
api_router.include_router(ws.router)            # /ws/*
```

### 2.4 数据库（15 张表：4 张核心业务表 + 6 张进化闭环表 + 1 张 LLM 用量表 + 4 张交易表）

| 表 | 用途 | 关键字段 |
|---|---|---|
| `watchlist` | 自选股 | symbol（唯一） / name / note / sort_order |
| `alerts` | 提醒 | symbol / alert_type / target_price / triggered / feishu_sent |
| `positions` | 手动/真实持仓 | symbol / quantity / avg_cost / stop_loss_pct / take_profit_pct / **last_alert_at** / **last_alert_kind** |
| `analysis_cache` | Agent 缓存 | symbol（唯一） / result(JSON) / **updated_at** |
| `model_versions` | 推荐模型版本 | name / version / status / config(JSON) / metrics(JSON) |
| `scan_runs` | 扫描批次 | params / market_status / tier counts / result_count / model_version_id |
| `stock_predictions` | 可验证预测样本 | symbol / horizon_days / probability / target_return_pct / due_at / status |
| `prediction_outcomes` | 到期验证结果 | close_return_pct / max_return_pct / hit_target / hit_stop / success |
| `evolution_runs` | 进化运行记录 | evaluated_predictions / success_rate / brier_score / promoted |
| `model_metrics` | 周期聚合指标 | horizon_days / sample_count / success_rate / calibration_error |
| `llm_usage` | LLM 用量记录 | provider / model / prompt_tokens / completion_tokens / estimated_cost_usd |
| `trading_accounts` | 交易账户快照 | account_id / broker / cash / available_cash / market_value / total_asset |
| `trading_positions` | 交易账户持仓 | account_id / broker / symbol / quantity / available_quantity / avg_cost / market_value |
| `trade_orders` | 订单记录 | client_order_id / broker_order_id / side / quantity / price / status / source |
| `trade_fills` | 成交记录 | order_id / symbol / side / quantity / price / amount / filled_at / evolution_recorded_at |

加粗字段是后期为修复 bug 加的，启动时 `_migrate_legacy_columns()` 自动 `ALTER TABLE` 兼容旧库。

### 2.5 前端页面（10 个）

| 页面 | 路径 | 职责 |
|---|---|---|
| RealtimeAdvisor | `/advisor` | 首页实时推荐，使用 AI 终审 + 进化模型概率 |
| Overview | `/overview` | 涨跌幅榜 / 自选股 / 详情抽屉 |
| Market | `/market` | K 线 + 量能 + 新闻 + 实时推送 |
| Scanner | `/scanner` | **核心**：三层漏斗扫描 + AI 推荐 + AI 否决展示 + 进化概率 |
| Evolution | `/evolution` | 模型进化中枢：验证预测、查看胜率、生成/启用候选模型 |
| Agent | `/agent` | 单股深度分析（决策仪表盘） |
| Alerts | `/alerts` | 价格提醒列表 |
| Positions | `/positions` | 持仓管理 + 实时盈亏 |
| Trading | `/trading` | 交易闭环：账户、交易持仓、预览风控、模拟/QMT 下单、订单和成交记录 |
| Settings | `/settings` | 平台 API Key / LLM 配置（API Key / 模型 / 温度） |

App.vue 用 `<keep-alive :include>` 缓存全部页面，切换不丢状态。

---

## 三、关键设计决策

### 3.1 为什么是三层漏斗

最初版本只有 Tier-1 单层（技术评分），存在三个问题：
1. 同质策略重复加分（多头排列+MACD+站MA20 实质是同一现象）
2. 看不到 PE / 流通市值，会把 ST 股 / 庄股 / 估值离谱的股推荐出来
3. 与 Agent 单股分析结论矛盾

引入 Tier-2 解决质量过滤，引入 Tier-3 让 LLM 做最终决策（与单股分析一致）。

### 3.2 Tier-3 不重复调工具，复用 Tier-1+Tier-2 数据

`SuperAnalystAgent.run` 接受 `context["preloaded_observations"]` 参数：

```python
# scanner_service.py 内
preloaded = [
    ToolResult(name="get_realtime_quote", output=quote_data),
    ToolResult(name="get_daily_bars", output={"bars": bars[-30:]}),
    ToolResult(name="get_technical_features", output=feat),  # Tier-1 已算的指标
    ToolResult(name="detect_chart_pattern", output=pattern_data),  # 命中策略
    ToolResult(name="get_support_resistance", output={...}),
    ToolResult(name="search_news", output={"news": [
        {"title": "扫描器整合数据", "content": "PE/市值/主力/换手/龙虎榜"},
        {"title": "行业景气度", "content": "Top10 热门行业"},
        {"title": "技术形态命中", "content": "11 种策略命中情况"},
    ]}),
    ToolResult(name="analyze_news_sentiment", output={...}),
]
agent.run(goal, context={"symbol": symbol, "preloaded_observations": preloaded})
```

LLM 看到的数据 = Tier-1 指标 + Tier-2 基本面 + 行业景气度。**不再重复调外部 API**，速度提升 2-3 倍。

### 3.3 4 维独立评分（不再合并）

之前把技术分 + 基本面分 + AI 置信度强行合并成一个数字，丢失了"哪个维度强、哪个维度弱"的关键信息。

**现在每只股票独立显示 8 个分**：
- 技术分（0-100）
- 基本面分（0-25，PE 10 + 市值 10 + PB 5）
- 资金面分（0-25，主力净流入 12 + 换手 5 + 龙虎榜机构 8）
- 行业景气分（0-15，所属行业排名 + 行业涨跌幅 + 行业净流入）
- 北向资金分（0-15，北向 5 日增持市值 + 市值增幅 + 占流通股比变化）
- 机构研报分（0-15，近 30 天研报数量 + 买入评级 + 正面评级 + 覆盖机构数）
- 减持风险分（0-15，近 90 天董监高/相关人员减持次数 + 金额 + 最近日期；分数越高风险越大）
- AI 把握度（0-100）

排序按 `(BUY > HOLD > 其他) → 综合可信度` 两级排；综合可信度会参考技术、基本面、资金面、行业景气、北向资金、机构研报、减持风险和 AI 置信度，不再依赖单一技术分。

### 3.4 LLM 失败优雅降级

LLM 余额不足/限流/超时时，scanner 检测响应是否以 `[LLM error:` 开头或解析后是 `raw_response` 兜底模式，标记 `used_llm=false`，走规则引擎给出 BUY/HOLD/SELL/WATCH。

返回结果中 `llm_status` 字段：
- `ok`：所有 LLM 调用成功
- `partial`：部分失败
- `all_failed`：全部失败
- `disabled`：用户关闭 / LLM 未配置

前端根据状态显示红色或黄色 banner 引导用户。

### 3.5 行情双层缓存

`market_service.py` 维护两套缓存：

| 缓存 | TTL | 数据源 | 用途 |
|---|---|---|---|
| `_precise_cache` | 3s | 新浪 `hq.sinajs.cn`（批量 URL） | 自选股+持仓精准跟踪 |
| `_market_cache` | 30s | AKShare `stock_zh_a_spot`（新浪源） | 全市场涨跌榜+扫描器候选过滤 |

`_precise_symbols` 限制最多 80 只，超过按 LRU 淘汰，避免新浪 URL 拼接超长。`get_single_quote` 用 `persistent=False` 标记不入精准集合（避免扫描器分析 200 只股票时全部进集合）。

### 3.6 keep-alive + 路由 query 自动触发

App.vue 包了 `<keep-alive>`，缓存 `RealtimeAdvisor / Overview / Market / Scanner / Evolution / Agent / Alerts / Positions / Settings`，每个 view 都用 `defineOptions({ name: 'X' })` 命名。

Agent.vue 同时监听 3 个生命周期：
- `onMounted`：首次进入
- `onActivated`：keep-alive 激活
- `watch(route.query.symbol + t)`：同 query 重复跳转

跳转时带 `t: Date.now()` 时间戳确保 `watch` 触发，从扫描器/总览/行情跳过来都能自动开始分析。

### 3.7 飞书发送异步 fire-and-forget

`feishu_service.py` 内置 `ThreadPoolExecutor(max_workers=4)`，所有 `send_*` 函数把请求 submit 到线程池就立即返回 `True`，**不等飞书 webhook 网络响应**。这样：
- 飞书网络抖动 5s 也不会阻塞 quote_loop（每 3s 推送）
- 多个提醒可以并发发送

### 3.8 自动进化闭环

扫描器完成后会调用 `evolution_service.record_scan_result()`：
- 每次扫描写入 `scan_runs`
- 每只推荐股生成 3 / 5 / 10 / 20 日预测样本，写入 `stock_predictions`
- 每条预测包含当时价格、目标涨幅、止损比例、上涨概率、特征快照和原始推荐结果
- Scanner 可选择“自动最佳 / 3 / 5 / 10 / 20 日”目标周期；进化模型会在最终 `top_n` 截断前对完整推荐池排序，避免高上涨概率股票被早期排序截掉
- Scanner 缓存键包含 `llm_top_n`、目标周期、策略和过滤参数，避免调参后误命中旧结果
- `/evolution/validate` 在预测到期后拉取 K 线，判断是否先触发目标价或止损，写入 `prediction_outcomes`
- `/evolution/evolve` 基于已验证样本计算命中率、平均收益、Brier score、校准误差，并生成候选模型；`promote=true` 时切换为 active，后续扫描立即使用新权重
- FastAPI lifespan 会启动自动验证循环，默认每日运行一次；`QUANT_EVOLUTION_VALIDATE_INTERVAL_SECONDS=0` 可关闭；`QUANT_EVOLUTION_VALIDATE_TIME=HH:MM` 可按服务器本地时间每天固定触发
- FastAPI lifespan 也支持自动采样循环；`QUANT_EVOLUTION_AUTO_SCAN_ENABLED=true` 后会按 `QUANT_EVOLUTION_AUTO_SCAN_INTERVAL_SECONDS` 定时运行 Scanner，自动写入新的 scan run 和 pending prediction 样本
- 自动采样默认关闭，且 `QUANT_EVOLUTION_AUTO_SCAN_ENABLE_LLM=false` 默认不跑 LLM，避免后台任务产生不可控耗时和费用；可在“模型进化”控制台保存运行时参数并重启后台循环
- `/evolution/auto-scan` 可手动触发一次同样的自动采样流程，用于立即产生新预测样本并检查最近一次采样状态
- 自动验证循环会先调用 `record_trade_fills()`：BUY 成交会转成执行预测样本，SELL 成交会按同账户同股票 FIFO 买入 fill 组和卖出数量结算未验证执行预测，直接写入“真实退出是否赚钱”的 outcome
- 自动验证循环会继续调用受控 `auto_evolve_cycle()`：样本量、命中率、平均收益、Brier score、校准误差全部达标才自动晋升；新模型表现跌破回滚阈值时自动恢复父版本
- `/evolution/auto-cycle` 可手动触发同一套受控自动进化检查；决策会写入 `evolution_runs`，状态包括 `auto_blocked` / `auto_promoted` / `auto_rolled_back`
- `/evolution/config` 支持查看/保存运行时自动验证、失败告警、自动采样和自动进化阈值；保存后会重启后台循环并立即生效，运行时配置落盘到 `data/runtime_config.json`
- 后台自动验证/进化、自动采样失败时可通过飞书发送失败告警；`QUANT_EVOLUTION_FAILURE_ALERT_ENABLED=true` 默认开启，`QUANT_EVOLUTION_FAILURE_ALERT_COOLDOWN_SECONDS=3600` 按失败类型冷却，避免数据源故障时刷屏
- 自动采样参数可用环境变量配置：`QUANT_EVOLUTION_AUTO_SCAN_ENABLED`、`QUANT_EVOLUTION_AUTO_SCAN_INTERVAL_SECONDS`、`QUANT_EVOLUTION_AUTO_SCAN_TOP_N`、`QUANT_EVOLUTION_AUTO_SCAN_MIN_SCORE`、`QUANT_EVOLUTION_AUTO_SCAN_CANDIDATE_POOL`、`QUANT_EVOLUTION_AUTO_SCAN_ENABLE_FUNDAMENTAL`、`QUANT_EVOLUTION_AUTO_SCAN_ENABLE_LLM`、`QUANT_EVOLUTION_AUTO_SCAN_LLM_TOP_N`、`QUANT_EVOLUTION_AUTO_SCAN_TARGET_HORIZON_DAYS`
- 自动进化阈值也可用环境变量配置：`QUANT_EVOLUTION_AUTO_EVOLVE_MIN_SAMPLES`、`QUANT_EVOLUTION_AUTO_PROMOTE_MIN_SUCCESS_RATE`、`QUANT_EVOLUTION_AUTO_PROMOTE_MIN_AVG_RETURN_PCT`、`QUANT_EVOLUTION_AUTO_PROMOTE_MAX_BRIER_SCORE`、`QUANT_EVOLUTION_AUTO_PROMOTE_MAX_CALIBRATION_ERROR`
- 自动回滚阈值可用环境变量配置：`QUANT_EVOLUTION_AUTO_ROLLBACK_MIN_SAMPLES`、`QUANT_EVOLUTION_AUTO_ROLLBACK_MIN_SUCCESS_RATE`、`QUANT_EVOLUTION_AUTO_ROLLBACK_MIN_AVG_RETURN_PCT`、`QUANT_EVOLUTION_AUTO_ROLLBACK_MAX_BRIER_SCORE`
- `/evolution/compare` 默认比较最近两次扫描，返回新增、连续推荐和掉队股票
- LLMClient 会记录 provider 返回的 token usage，`/llm/usage` 返回最近调用、token 和可配置价格估算；价格通过 `QUANT_LLM_INPUT_COST_PER_MILLION_TOKENS` / `QUANT_LLM_OUTPUT_COST_PER_MILLION_TOKENS` 配置

### 3.9 交易闭环

主 API 现在提供统一交易入口 `/trading/*`：
- `QUANT_TRADING_MODE=paper`（默认）：本地模拟盘，订单立即成交，写入 `trade_orders` / `trade_fills`，并同步更新独立的 `trading_positions`，不污染手动 `positions`
- `QUANT_TRADING_MODE=qmt`：通过 `QUANT_QMT_GATEWAY_URL` 转发到 Windows QMT Gateway，并把网关返回的订单状态落入本地订单表；`/trading/sync` 可同步 Gateway 账户、持仓、订单并按成交数量差额幂等生成本地成交
- QMT 模式下预览和下单必须先有本地同步账户快照；未执行 `/trading/sync` 时会拒绝并返回 `requires_sync`，避免误用模拟盘现金/持仓做实盘风控
- `QUANT_PAPER_INITIAL_CASH`：模拟盘初始现金，默认 100 万
- `QUANT_QMT_GATEWAY_API_KEY`：可选，转发 QMT Gateway 时发送 `X-API-Key`
- `QUANT_TRADING_BLOCK_ST_BUY=true`：默认拦截 ST 股票买入
- `QUANT_TRADING_SINGLE_STOCK_MAX_WEIGHT=0.15`：单股目标仓位上限
- `QUANT_TRADING_DAILY_TURNOVER_LIMIT=0.50`：单日成交额/总资产上限
- `QUANT_TRADING_ENFORCE_HOURS=false`：是否强制交易时段校验，默认关闭以便模拟盘和测试

前端 `/trading` 页面支持：
- 账户资产/现金/持仓市值
- 当前交易持仓（与手动持仓页隔离）
- 手动同步 QMT 账户/持仓/订单/成交
- 下单前预览风控（现金、持仓、A 股规则、涨跌停、ST、单股仓位、日成交额）
- 提交买入/卖出
- 订单列表和成交列表
- Scanner 卡片可直接跳到 Trading，自动带入股票、建议买入价和推荐理由

---

## 四、已修复的关键 Bug 历史

记录下来给后续维护者参考，避免重复踩坑：

### 致命级（生产中必爆）

1. **持仓告警每 3 秒重复推送飞书**（已修）
   - 现象：触发一次止损后，每 3 秒（quote_loop 周期）满足条件再推送一次，一晚刷上千条
   - 修复：`PositionORM` 加 `last_alert_at`/`last_alert_kind`，DB 持久化 + 内存 2 小时冷却双层去重

2. **启动瞬间 price=0 → 全部持仓被误判 -100% 触发止损**（已修）
   - 现象：服务启动时市场缓存为空，price=0，pnl_pct = -100%，所有持仓瞬间触发止损
   - 修复：`alert_service.py` 加 `if price <= 0: continue`

3. **bootstrap.py 引用幻影 ORM**（已修）
   - 现象：bootstrap.py 还 import `InstrumentORM` / `RecommendationORM` 等已删除的类，调用即 ImportError
   - 修复：删除 22 个 dead service + 16 个 dead route + 11 个 dead schema

4. **LLM 配置多 worker 不同步**（已修）
   - 现象：用户改 API Key 只对一个 worker 生效，其他 worker 用旧 key
   - 修复：`runtime_config.py` 基于文件 mtime 自动重载，写入用 `tmp.replace()` 原子化 + chmod 0o600

### 高级（影响功能正确性）

5. **MACD DEA 用 `dif * 0.9` 假算**（已修）
   - 修复：`scanner_service._macd()` 用标准 12/26/9 EMA 计算

6. **强势股目标价低于买入**（已修）
   - 修复：`target1 = max(target1, entry_mid * 1.03)` + `target2 > target1 * 1.05` + `stop_loss < entry_low` 兜底

7. **K 线 today_bar 与历史 K volume 单位混乱**（已修）
   - 现象：腾讯 K 线 `amount` 字段实为「手数」（1 手=100 股），代码当成股数
   - 修复：乘 100 转股数，估算成交额 = 收盘价 × 股数

8. **周/月 K 线 volume 字段丢失**（已修）
   - 修复：`_resample_kline` 同时聚合 amount 和 volume

9. **keep-alive 下 setInterval 不会被清理**（已修）
   - 现象：onUnmounted 不会触发，定时器永远在跑
   - 修复：用 `onActivated` / `onDeactivated` 启停 setInterval

10. **scanner 与 Agent 不一致**（已修，本次重构）
    - 见 §3.2

### 中级（边界情况）

11. **一字板 pos_in_20d=50 误判健康**：改返回 100
12. **涨跌停板硬编码 ±10%**：按板块识别（北交所 30% / 创业板&科创板 20% / ST 5% / 主板 10%）
13. **删除持仓不清相关提醒**：`positions.delete_position` 同时 `delete AlertORM` + `reset_position_alert_state`
14. **SQLite 未启用 WAL**：`session.py` 用 `event.listens_for(engine, 'connect')` 设置
15. **analysis_cache 无 TTL**：加 `updated_at` 列 + `is_stale` 标志（>6h）
16. **symbol 大小写不规范**：watchlist/positions 写库前 `_normalize_symbol`

### 完整修复清单

详见 git commit 历史：
```bash
git log --oneline
# aa650f8 feat(scanner): 三层漏斗第二轮重构，解决 13 项设计漏洞
# cfdf520 feat: 潜力扫描升级为三层漏斗+AI 终审
# 2dc22f9 fix(agent): 重写决策天平
# 41aa24b fix: 全面修复 32 项逻辑漏洞 + 潜力扫描升级
# b94f97d feat: 重构为 AlphaAgent (A股智能助手)
```

---

## 五、各服务工作机制详解

### 5.1 market_service.py

**两个后台线程**（`ensure_cache_running()` 在 lifespan 启动）：

```python
# 精准行情线程（3s 刷新）
_precise_refresh_loop:
    while True:
        symbols = list(_precise_symbols)  # 自选股+持仓
        if symbols:
            data = _fetch_precise(symbols)  # 新浪批量 URL
            _precise_cache.update(data)
        sleep(3)

# 全市场行情线程（30s 刷新）
_market_refresh_loop:
    # 启动立即拉一次
    _market_cache = _fetch_market_all()
    while True:
        sleep(30)
        _market_cache = _fetch_market_all()  # AKShare 新浪 spot
```

**K 线接口**：腾讯 `stock_zh_a_hist_tx`（稳定）+ 拼接今日实时 K 线。日 K 直接返回，周/月 K 通过 `_resample_kline` 聚合。

### 5.2 scanner_service.py

完整流程见 §3.2-3.3。关键参数：

```python
scan_potential_stocks(
    top_n=20,                      # 最终输出数量
    min_score=50,                  # Tier-1 最低分
    candidate_pool=120,            # Tier-1 深度分析候选数量
    use_cache=True,                # 5 分钟扫描结果缓存
    enable_fundamental=True,       # 是否启用 Tier-2
    enable_llm=True,               # 是否启用 Tier-3
    llm_top_n=12,                  # Tier-3 最多 LLM 调用数（控制成本）
    progress_callback=...,         # 进度回调（WebSocket）
)
```

**LLM 调用并发**：max_workers=4（避免触发 OpenAI/DeepSeek 限流），每只 timeout=180s。

**结果缓存 key**：`top{n}_min{s}_pool{p}_req{required_strategies}_f{fund}_l{llm}`，5 分钟 TTL。

### 5.3 fundamental_service.py

**4 个独立缓存**：
- `_info_cache`：单股 PE/PB/市值/行业/上市日期（6 小时 TTL）
- `_market_flow_cache`：全市场主力资金流（1 小时 TTL，一次拉全部）
- `_northbound_cache`：全市场北向 5 日增减持排行（1 小时 TTL，一次拉全部）
- `_research_cache`：个股研报评级摘要（24 小时 TTL，只对 Tier-2 候选池调用）
- `_insider_change_cache`：全市场董监高/相关人员近 90 天持股变动（6 小时 TTL，一次拉全部）
- `_lhb_cache`：龙虎榜（24 小时 TTL，失败优雅降级）
- `_hot_industries` / `_hot_concepts`：行业景气度（30 分钟 TTL）

**关键函数**：
- `evaluate_fundamental(symbol)`：返回 `{hard_blocks, quality, flow_score, industry_score, northbound_score, research_score, insider_reduction_score, quality_items, flow_items, industry_items, northbound_items, research_items, insider_reduction_items, industry_rank, info, fund_flow, northbound_flow, research_rating, insider_reduction, lhb}`
- `get_hot_industries(top_n)`：行业排名 + 涨幅 + 资金流
- `get_industry_rank(industry_name)`：把单股所属行业映射到全市场行业景气排名，供扫描器排序、LLM 上下文和前端展示使用
- `get_northbound_flow(symbol)`：从北向 5 日个股增减持排行中读取单股外资持仓变化
- `get_research_rating(symbol)`：汇总近 30 天研报、评级、覆盖机构和最新报告
- `get_insider_reduction(symbol)`：汇总近 90 天董监高/相关人员减持风险；严重大额减持会进入 `hard_blocks`

### 5.4 alert_service.py

```python
check_price_alerts(db, quotes):
    for alert in 未触发的提醒:
        if price <= 0: continue       # 启动保护
        if hit:
            alert.triggered = True    # DB 标记防重发
            feishu.send_price_alert() # 异步发送
            triggered.append(alert)

check_position_alerts(db, quotes):
    for pos in positions:
        if price <= 0: continue
        # 双层冷却：内存 _position_alert_state（2h）+ DB last_alert_at（重启不重发）
        # 触发后写 DB last_alert_at + last_alert_kind
```

`reset_position_alert_state(symbol)` 在 positions delete/upsert 时调用，让新成本基线立即生效。

### 5.5 ws.py（WebSocket 推送）

启动一个 `_quote_loop`（asyncio task）每 3s 执行：

```python
async def _quote_loop():
    while True:
        if manager.count() == 0:  # 没客户端就跳过
            sleep
            continue
        # 拉取所有 watchlist + positions 的实时行情
        quotes = market_service.get_realtime_quotes(symbols)
        await manager.broadcast("quotes", quotes)
        # 同时检查提醒触发
        triggered = await asyncio.to_thread(alert_service.check_*)
        if triggered:
            await manager.broadcast("alerts", triggered)
        sleep(3)
```

### 5.6 LLM 配置（runtime_config.py）

```python
get_override():
    # 检查文件 mtime，变了就重新加载（多 worker 自动同步）
    if disk_mtime > _OVERRIDE_MTIME:
        _OVERRIDE = _load_from_disk()
        _OVERRIDE_MTIME = disk_mtime
    return _OVERRIDE

set_override(...):
    # 原子写入：写 .tmp 再 rename
    tmp.write(json)
    tmp.replace(target)
    chmod(target, 0o600)  # 只允许当前用户读
```

LLMClient 用方法链：`runtime_config > .env > 默认值`。前端通过 `/api/v1/llm/config` POST 修改后立即生效。

---

## 六、前端关键约定

### 6.1 组件命名

每个 view 必须用 `defineOptions({ name: 'X' })`，否则 keep-alive 不会正确缓存。

### 6.2 路由跳转带时间戳

跳到 Agent 页时带 `t: Date.now()` 触发 watch：

```js
router.push({
  path: '/agent',
  query: { symbol, name, t: Date.now() }
})
```

否则 keep-alive 缓存的 Agent 页 `onActivated` 不会触发新分析。

### 6.3 localStorage 持久化

Scanner 扫描结果保存到 `localStorage['scanner:last_result_v1']`：
- 切页/刷新/关浏览器都不丢
- 含选中策略+参数+时间戳
- 「清空记录」按钮可手动清

### 6.4 颜色规范（A 股习惯）

- 涨：红 `#f56c6c`
- 跌：绿 `#67c23a`
- 暗色背景：`#1a1a2e` / 边框 `#2a2a4a` / 文字 `#c0c4cc`

---

## 七、运维与故障排查

### 7.1 启动失败

1. **`ImportError: No module named ...`**
   - 检查 Python 版本是否 3.12+
   - 检查 `pip install -e .` 是否完整

2. **`sqlite3.OperationalError: no such column ...`**
   - DB 自动迁移失败。手动执行：
   ```bash
   python3 -c "from apps.api.app.db.session import init_db; init_db()"
   ```
   - 或删除 `var/quant.db` 让其重建

3. **行情拉不到（启动后市场缓存空）**
   - 检查 AKShare 版本 `>= 1.17`
   - 检查网络（新浪 hq.sinajs.cn 在国外可能不可达）
   - 看后台日志：`首次加载全市场行情缓存...`

### 7.2 LLM 相关

1. **扫描器全部返回规则引擎结果**
   - 前端会显示红色 banner
   - 检查设置页 LLM 是否配置正确
   - 检查 LLM 余额：DeepSeek `https://platform.deepseek.com/usage`
   - 试用 `POST /api/v1/llm/test?level=quick` 验证

2. **LLM 返回非 JSON**
   - 后台日志会有 `LLM 输出非 JSON 格式`
   - 通常是模型不支持中文 JSON 输出（如某些小模型），换 deepseek-chat 或 gpt-4o-mini

3. **多 worker 配置不同步**
   - 已修复：mtime 自动重载
   - 仍可手动重启 uvicorn

### 7.3 飞书提醒

1. **没收到提醒**
   - 优先检查设置页的飞书 Webhook 运行时配置；也可检查 `.env` 的 `QUANT_FEISHU_WEBHOOK_URL`
   - 试用 `POST /api/v1/notify/test`
   - 看后台日志的 `飞书消息发送成功 / 失败`

2. **提醒疯狂刷屏**（已修但记录）
   - 价格提醒：检查 alerts 表的 `triggered` 字段，应该已是 True
   - 持仓提醒：检查 positions 表的 `last_alert_at`，应该已写入

### 7.4 性能

1. **扫描超过 8 分钟**
   - 大概率是 LLM 调用慢，看 max_workers 是否 ≥ 4
   - 减少 `llm_top_n` 参数（默认 12，可降到 6）

2. **行情推送卡顿**
   - 检查飞书发送是否阻塞了 quote_loop（已修复，feishu 是 fire-and-forget）
   - 检查 WebSocket 连接数，过多客户端时考虑限制

---

## 八、安全注意

### 8.1 API Key 保护

- `data/llm_runtime.json` 和 `data/runtime_config.json` 文件权限 0600（已自动设置）
- `.gitignore` 已排除 `data/llm_runtime.json`、`data/runtime_config.json` 和 `data/*.db*`
- **千万不要**把 .env 或 data/ 提交到 git

### 8.2 飞书 Webhook

- Webhook URL 包含 token，泄露后任何人都能发消息
- Webhook URL 支持通过设置页运行时配置，接口只返回脱敏预览，不返回原文

### 8.3 认证

代码默认 `QUANT_AUTH_ENABLED=true`。本地开发如需无鉴权，必须在 `.env` 显式设置 `QUANT_AUTH_ENABLED=false`。生产环境应配置强随机 `QUANT_*_API_KEY`，并把 CORS 收敛到真实前端域名。

---

## 九、后续优化方向

按重要性排序：

### 高优先级

1. **LLM Cost 精细化**：当前已记录真实 token usage，并支持按环境变量估算费用；后续可按 provider/model 自动维护价格表
2. **自动定时验证增强**：当前已默认每日验证到期预测，且可在前端配置验证周期、固定验证时间、失败告警冷却和进化阈值；后续可补交易日历感知与节假日跳过
3. **历史扫描结果对比增强**：当前已支持最近两次扫描对比，后续可做任意日期/模型版本对比
4. **QMT 实盘验收**：当前主 API 已支持转发和手动同步 QMT Gateway，`XtQuantBackend` 已适配真实 `xtquant` 下单、撤单、订单、持仓和资金查询；后续需要在 Windows + QMT/miniQMT 物理机做模拟盘/小额实盘验收，并按真实返回字段校准状态映射

### 中优先级

5. **风控增强**：当前已接入 A 股规则、ST 拦截、单股仓位、日成交额限制、行业集中度、组合回撤、杠杆、波动率和调仓现金预算校验；后续补真实交易日历、节假日跳过、停牌/退市数据和 QMT 可卖数量实时预览
6. **扫描进度细化**：Scanner 已接 `/scanner/ws/scan` 且 WebSocket 会携带 API key 查询参数；后续可继续显示更细的候选池数量、LLM token 和单股耗时
7. **行业关联增强**：当前已显示所属行业、行业排名和景气分；后续可补概念板块关联和同业对比列表
8. **北向资金增强**：当前已接入 5 日北向增减持排行；后续可加入连续多日明细趋势和外资持股占比历史分位
9. **研报增强**：当前已接入近 30 天研报评级；后续可分析目标价上调/下调和盈利预测变化趋势
10. **交易复盘入模增强**：当前 BUY 成交会转成 evolution 执行样本，SELL 成交会按 FIFO 买入 fill 组和部分卖出数量结算执行预测；后续需要补止盈止损原因、交易计划执行情况和更细的持仓周期归因

### 低优先级

10. **多账户**：当前是单用户单库，多用户场景需要加 user_id
11. **手机端适配**：当前布局以桌面为主，移动端可继续优化
12. **支持港股 / 美股**：架构已经预留 symbol 后缀（.SH/.SZ/.HK 等），数据源需要适配
13. **回测 + 策略组合**：让用户保存自己的策略组合并跟踪

---

## 十、git 工作流

```bash
# 当前主分支
git checkout main

# 提交规范（Conventional Commits）
git commit -m "feat: ..."   # 新功能
git commit -m "fix: ..."    # bug 修复
git commit -m "refactor: ..." # 重构
git commit -m "docs: ..."   # 文档

# 推送
git push origin main
```

历史关键 commit：
- `b94f97d` 重构为 AlphaAgent (A股智能助手)（删除 19 表→4 表）
- `41aa24b` 全面修复 32 项逻辑漏洞
- `2dc22f9` Agent 决策天平重写（让 AI 主动给立场）
- `cfdf520` 潜力扫描升级为三层漏斗 + AI 终审
- `aa650f8` 三层漏斗第二轮重构（解决 13 项设计漏洞）

---

## 十一、联系方式与已知 Owner

> 项目作者：diminglucky  
> GitHub：https://github.com/diminglucky/AlphaAgent

**重要约定**：
- 这只是个人投资辅助工具，**不是金融机构产品**
- 不构成投资建议，所有买卖决策由用户自行承担
- 数据来源都是公开免费 API，不保证 100% 实时准确

---

## 附：常用命令速查

```bash
# 启动后端（开发）
uvicorn apps.api.app.main:app --reload --port 8000 --env-file .env

# 启动前端（开发）
cd apps/web && npm run dev

# 构建前端
cd apps/web && npm run build

# 清空扫描器缓存
curl -X DELETE http://127.0.0.1:8000/api/v1/scanner/cache

# 测试扫描（小规模，约 1 分钟）
curl -X POST http://127.0.0.1:8000/api/v1/scanner/scan \
  -H "Content-Type: application/json" \
  -d '{"top_n":5,"candidate_pool":40,"llm_top_n":5}'

# 测试 LLM 配置
curl -X POST http://127.0.0.1:8000/api/v1/llm/test?level=quick

# 查看运行状态
curl http://127.0.0.1:8000/api/v1/health
curl http://127.0.0.1:8000/api/v1/market/cache-status

# 查看数据库
sqlite3 var/quant.db
.tables
SELECT * FROM positions;
```

---

文档维护：每次重大改动同步更新本文档对应章节。
