"""SuperAnalystAgent — 顶级卖方研究员，全维度深度分析单只股票。

并行分析架构（Phase 1 并行 + Phase 2 LLM 综合）：
  Phase 1（并行，ThreadPoolExecutor，7个工具同时执行）：
    ├── get_realtime_quote      — 实时报价
    ├── get_daily_bars(60)      — 60 日 K 线
    ├── get_technical_features  — 技术指标
    ├── detect_chart_pattern    — K 线形态
    ├── get_support_resistance  — 支撑/阻力位
    ├── search_news             — 近期新闻
    └── analyze_news_sentiment  — 情绪评分

  Phase 2（单次 LLM 调用）：
    把 Phase 1 所有结果组装成一个超级 prompt，一次性交给 LLM 综合分析，
    输出结构化 JSON 报告。

相比 ReAct 串行循环（7次工具 + 7次LLM），并行方案只需：
  - 1 轮并行工具调用（耗时 = 最慢的那个工具，约 10-20s）
  - 1 次 LLM 调用（约 20-40s）
  总计约 30-60s，比串行快 2-3 倍。
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Optional

from libs.agents.base_agent import AgentRun, AgentStep
from libs.agents.skills import SkillRegistry, ToolCall, ToolResult, get_default_registry
from libs.llm_analyst.llm_client import LLMClient

log = logging.getLogger("quant.agent.super_analyst")

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM = """你是一名拥有 20 年经验的顶级卖方研究员，曾任职于高盛、中金公司，
擅长将技术分析、基本面研究、市场情绪与宏观研判融为一体，
**主动**为客户挖掘有上涨潜力的标的并给出**清晰、可执行的买入决策**。

## 角色定位

你不是"风险规避者"，而是"机会发现者"。客户找你是为了**赚钱**，不是只想听到"观望"。
- 你必须有立场。模棱两可的"WATCH"只在数据严重不足或矛盾时才输出。
- 找到信号 → 给 BUY；信号确实转坏 → 给 SELL；正在持仓且仍有上涨空间 → 给 HOLD。
- 严禁滥用 WATCH 当万能挡箭牌。

## 决策天平（关键）

下面任意 **3 条** 满足时倾向 BUY：
1. MA5 > MA10 > MA20（多头排列）或 MA20 向上拐头
2. 站上 MA20（偏离 ≤ +8%）且未严重超买（RSI ≤ 75）
3. MACD 多头（DIF > DEA 或 红柱）或刚金叉
4. 量比 ≥ 1.5 配合上涨，或 5 日成交额连续放大
5. 突破近期平台/前高，或回踩 MA10/MA20 不破
6. 价格在 20 日区间 30%-80% 位置（健康区间）
7. 大盘配合（上证趋势向上）或行业景气度上升

下面任意 **2 条** 满足且无明显多头信号时给 SELL：
- MACD 死叉 + 跌破 MA20
- RSI > 80 + 出现顶背离/吊颈线
- 放量下跌（量比 ≥ 1.5 + 跌幅 > 3%）
- 重大利空（业绩暴雷、监管处罚、公司治理问题）

**HOLD**：已持仓且趋势未坏（站稳 MA20 + MACD 不死叉），明确告诉用户继续持有的理由和何时减仓。

**WATCH**：仅当 ① 数据严重缺失 ② 多空信号严重打架（如多头排列但顶背离）才用。

## 七条实战经验（不是死规矩，是参考）

1. 大幅高开高走（涨 ≥ 7%）当日不追涨，但仍给 BUY 评级，建议明日回踩 MA5 介入
2. 多头排列 + 量价配合 = 强烈推荐买入
3. 回踩均线（MA10/MA20）支撑买点比突破买点风险更低，应优先推荐
4. 重大利空 + 跌破多重均线 才一票否决，单一负面新闻不足以否决技术面
5. 量价配合：上涨必须有量验证；横盘缩量是健康整理
6. 强势龙头股可放宽 1-3 条标准
7. 中线（1-4 周）持仓周期最适合大多数散户

## 分析框架

**Step 1 — 技术面诊断**（必须有具体数据支撑）
- 均线排列 + 多头/空头/震荡判断 + 乖离率
- RSI/MACD/KDJ + 形态学（金叉、突破、回踩、底部反转）
- 量价配合 + 量比
- 关键支撑/阻力位

**Step 2 — 消息面研判**
- 近期新闻情绪、负面事件量化
- 行业景气度

**Step 3 — 大盘环境**：上证/深证/创业板趋势 + 个股相对强度

**Step 4 — 综合决策与作战计划**
- 按上面的决策天平给出 BUY/SELL/HOLD/WATCH
- 区分「无持仓」和「有持仓」两种情况，分别给出操作建议
- 必须给出 4 档价格：理想买点 / 次要买点 / 止损 / 止盈
- 必须提供操作前的检查清单（5-8 项）
- 评估置信度（0-100）：信号充分时 70-85，一般时 55-70，模糊时 40-55

## 输出要求（严格 JSON，不要加 markdown 代码块之外的任何文字）

```json
{
  "action": "BUY|SELL|HOLD|WATCH",
  "confidence": 0-100,
  "current_price": float,
  "risk_level": "低|中|高",
  "time_horizon": "短线(1-5日)|中线(1-4周)|长线(1-3月)",

  "core_conclusion": {
    "one_sentence": "一句话结论（30字内，直击要害，明确表态）",
    "time_sensitivity": "时效性说明，如 '今日盘中可介入' / '等待回踩 MA20' / '观望 1-2 日'",
    "position_advice": {
      "no_position": "无持仓者：具体到价位的建议（如 '价格 5.10-5.15 区间分批建仓 30%，跌破 4.95 止损'）",
      "has_position": "有持仓者：具体建议（如 '持有，跌破 4.95 减半仓，反弹至 5.50 止盈一半'）"
    }
  },

  "battle_plan": {
    "ideal_buy": "理想买点价位 + 触发条件（如 '5.05-5.10，回踩 MA20 不破'）",
    "secondary_buy": "次要买点（如 '4.95-5.00，跌破 MA20 后企稳'）",
    "stop_loss": "止损价 + 触发条件（如 '4.90，跌破前低 + MA60'）",
    "take_profit": "止盈目标 + 触发条件（如 '5.50（短线）/ 5.80（中线）'）",
    "suggested_position": "建议仓位百分比（如 '20-30%' 或 '不超过 50%'）",
    "entry_plan": "建仓计划（如 '分 3 批：5.10/5.05/5.00 各 1/3'）",
    "risk_control": "风控要点（如 '严格止损，单股不超过总仓位 20%'）"
  },

  "action_checklist": [
    "执行前检查项1（如 '确认大盘当日未跌破 3000 点'）",
    "执行前检查项2",
    "执行前检查项3",
    "执行前检查项4",
    "执行前检查项5"
  ],

  "data_perspective": {
    "trend_status": {
      "ma_alignment": "均线排列描述（如 'MA5<MA10<MA20<MA60，空头排列'）",
      "is_bullish": false,
      "trend_score": 35,
      "trend_desc": "趋势强度说明"
    },
    "price_position": {
      "current_price": float,
      "ma5": float, "ma10": float, "ma20": float, "ma60": float,
      "bias_ma5": float,
      "bias_ma20": float,
      "bias_status": "正常|偏离过大|偏离合理",
      "support_level": float,
      "resistance_level": float
    },
    "volume_analysis": {
      "volume_ratio": float,
      "volume_status": "放量|缩量|正常",
      "volume_meaning": "成交量含义解读（如 '量比 19.2× 异常放大，可能是恐慌盘抛售'）"
    },
    "rsi_status": "超买|超卖|中性 + 数值",
    "macd_status": "金叉|死叉|多头|空头 + 描述"
  },

  "intelligence": {
    "sentiment_summary": "市场情绪一句话总结",
    "earnings_outlook": "业绩预期/基本面评估",
    "risk_alerts": ["风险点1（含具体数据）", "风险点2", "风险点3"],
    "positive_catalysts": ["利好1", "利好2", "利好3"],
    "latest_news": "最新值得关注的消息"
  },

  "summary": "200字综合结论",
  "technical_analysis": "详细技术面分析150字+",
  "news_analysis": "消息面分析100字+",
  "market_analysis": "大盘环境分析80字+",
  "risk_analysis": "风险提示80字+",
  "key_points": ["要点1（含数据）", "要点2", "要点3", "要点4", "要点5"],
  "catalysts": ["催化剂1", "催化剂2", "催化剂3"],
  "risk_factors": ["风险1", "风险2", "风险3"],

  "buy_price_low": float,
  "buy_price_high": float,
  "stop_loss": float,
  "take_profit": float,

  "support_levels": [float, float, float],
  "resistance_levels": [float, float, float],
  "patterns_detected": ["形态1", "形态2"]
}
```

## 纪律约束

- 所有价格数字必须来自工具返回，严禁臆造
- 置信度须与信号数量和质量匹配，**信号充分时不要谦虚地给低分**
- WATCH 仅在数据严重不足或多空冲突极大时使用，不允许"模棱两可式 WATCH"
- 风险提示必须客观，不得为迎合用户而淡化风险
- core_conclusion 和 battle_plan 必须给出具体到小数点后两位的价格，不能用区间或模糊表述
- action_checklist 必须实操化，不能写"注意风险"这种空话
- **重要**：客户付费请你做决策，不是只为听"观望"。给立场，给计划，给数字。
"""


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------

class SuperAnalystAgent:
    """并行超级金融分析师 Agent。

    Phase 1：并行调用所有工具（ThreadPoolExecutor，max_workers=7，timeout=30s per tool）
    Phase 2：单次 LLM 调用综合所有数据，或规则引擎兜底

    用法::

        agent = SuperAnalystAgent()
        run = agent.run("深度分析 600028.SH 中国石化", context={"db": db_session})
        result = run.final_answer   # dict
    """

    name = "super_analyst"

    # 工具列表（全部并行执行）
    _TOOLS = [
        ("get_realtime_quote",     lambda sym: {"symbol": sym}),
        ("get_daily_bars",         lambda sym: {"symbol": sym, "days": 60}),
        ("get_technical_features", lambda sym: {"symbol": sym}),
        ("detect_chart_pattern",   lambda sym: {"symbol": sym}),
        ("get_support_resistance", lambda sym: {"symbol": sym}),
        ("search_news",            lambda sym: {"symbol": sym, "days": 7}),
        ("analyze_news_sentiment", lambda sym: {"symbol": sym, "days": 7}),
    ]

    def __init__(
        self,
        registry: Optional[SkillRegistry] = None,
        llm: Optional[LLMClient] = None,
    ) -> None:
        self.registry = registry or get_default_registry()
        self.llm = llm or LLMClient()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, goal: str, context: Optional[dict] = None) -> AgentRun:
        """执行完整分析流程，返回 AgentRun（final_answer 为 dict 报告）。"""
        run_id = uuid.uuid4().hex[:12]
        ctx = dict(context or {})
        run = AgentRun(
            run_id=run_id,
            agent_name=self.name,
            goal=goal,
            llm_powered=self.llm.is_llm_available(),
        )
        t0 = time.monotonic()

        try:
            # 1. 提取股票代码
            symbol = ctx.get("symbol") or _extract_symbol(goal)
            if not symbol:
                raise ValueError(f"无法从 goal 中提取股票代码: {goal!r}")

            # 2. Phase 1：并行调用所有工具
            #    （扫描器场景下可以传入 preloaded_observations 跳过工具调用，
            #     避免重复拉取 K 线/行情/新闻，且让 LLM 看到与 Tier-1/Tier-2 一致的指标）
            preloaded = ctx.get("preloaded_observations")
            if preloaded:
                observations = preloaded
            else:
                observations = self._run_tools_parallel(symbol, ctx, run)

            # 3. Phase 2：LLM 综合 or 规则引擎
            if run.llm_powered:
                final = self._llm_synthesize(symbol, goal, observations, run)
            else:
                final = _summarize_by_rules(goal, observations)

            run.final_answer = final
            run.status = "success"

        except Exception as exc:
            log.warning("super_analyst run failed: %s", exc, exc_info=True)
            run.final_answer = {"error": str(exc), "action": "WATCH", "confidence": 0}
            run.status = "failed"
        finally:
            run.duration_ms = (time.monotonic() - t0) * 1000
            run.finished_at = datetime.now()

        return run

    # ------------------------------------------------------------------
    # Phase 1：并行工具调用
    # ------------------------------------------------------------------

    def _run_tools_parallel(
        self, symbol: str, ctx: dict, run: AgentRun
    ) -> list[ToolResult]:
        """用 ThreadPoolExecutor 并行执行所有工具，返回结果列表。"""
        calls = [
            ToolCall(name=name, arguments=arg_fn(symbol))
            for name, arg_fn in self._TOOLS
        ]

        results: dict[str, ToolResult] = {}
        t0 = time.monotonic()

        with ThreadPoolExecutor(max_workers=7, thread_name_prefix="analyst") as pool:
            future_to_call = {
                pool.submit(self.registry.execute, call, context=ctx): call
                for call in calls
            }
            for future in as_completed(future_to_call):
                call = future_to_call[future]
                try:
                    result = future.result(timeout=30)
                except Exception as exc:
                    result = ToolResult(
                        call_id=None,
                        name=call.name,
                        output=None,
                        error=f"timeout/error: {exc}",
                    )
                results[call.name] = result
                run.tool_calls_made += 1

                run.steps.append(AgentStep(
                    step=len(run.steps),
                    role="tool_result",
                    content={
                        "name": call.name,
                        "ok": result.error is None,
                        "output": result.output,
                        "error": result.error,
                        "duration_ms": round(result.duration_ms, 1),
                    },
                ))

        elapsed = round((time.monotonic() - t0) * 1000, 1)
        log.info(
            "super_analyst: 并行工具调用完成 %d/%d，耗时 %.0fms",
            sum(1 for r in results.values() if r.error is None),
            len(calls),
            elapsed,
        )

        # 按原始顺序返回
        return [results[call.name] for call in calls if call.name in results]

    # ------------------------------------------------------------------
    # Phase 2a：LLM 综合分析
    # ------------------------------------------------------------------

    def _llm_synthesize(
        self,
        symbol: str,
        goal: str,
        observations: list[ToolResult],
        run: AgentRun,
    ) -> dict:
        """把所有工具结果组装成超级 prompt，一次性交给 LLM。"""

        # 提取各工具结果
        obs_map = {o.name: o.output for o in observations if o.error is None and o.output}

        quote   = obs_map.get("get_realtime_quote") or {}
        feat    = obs_map.get("get_technical_features") or {}
        pattern = obs_map.get("detect_chart_pattern") or {}
        sr      = obs_map.get("get_support_resistance") or {}
        news    = obs_map.get("search_news") or {}
        sent    = obs_map.get("analyze_news_sentiment") or {}
        bars    = obs_map.get("get_daily_bars") or {}

        # 大盘数据
        mkt = _get_market_context()

        # 近10日K线文本
        recent_bars_text = ""
        if isinstance(bars, dict) and bars.get("bars"):
            for b in bars["bars"][-10:]:
                recent_bars_text += (
                    f"  {b.get('date', '')}: "
                    f"开{b.get('open', 0):.2f} "
                    f"高{b.get('high', 0):.2f} "
                    f"低{b.get('low', 0):.2f} "
                    f"收{b.get('close', 0):.2f} "
                    f"涨跌{b.get('change_pct', 0):+.2f}%\n"
                )
        if not recent_bars_text:
            recent_bars_text = "  暂无K线数据\n"

        # 新闻文本
        news_text = ""
        if isinstance(news, dict) and news.get("articles"):
            for n in news["articles"][:8]:
                news_text += (
                    f"  [{n.get('time', '')[:16]}] "
                    f"{n.get('title', '')}（{n.get('source', '')}）\n"
                )
        if not news_text:
            news_text = "  暂无近期相关新闻\n"

        # 形态文本
        patterns_text = ""
        if isinstance(pattern, dict) and pattern.get("patterns"):
            for p in pattern["patterns"]:
                patterns_text += f"  • {p.get('name', '')}: {p.get('desc', '')}\n"
        if not patterns_text:
            patterns_text = "  未识别到明显形态\n"

        price = _safe_float(quote, "price") or _safe_float(feat, "current") or 0.0

        user_prompt = f"""请对以下 A 股进行深度专业分析：

═══════════════════════════════════════
【基本信息】
股票：{quote.get('name', symbol)}（{symbol}）
当前价格：¥{price:.2f}
今日涨跌：{quote.get('change_pct', 0):+.2f}%（{quote.get('change', 0):+.2f}元）
今开：{quote.get('open', 0):.2f}  最高：{quote.get('high', 0):.2f}  最低：{quote.get('low', 0):.2f}
成交额：{(quote.get('turnover') or 0) / 1e8:.2f}亿元

═══════════════════════════════════════
【大盘环境】
{mkt}

═══════════════════════════════════════
【技术指标】
均线：MA5={feat.get('ma5', 'N/A')}  MA10={feat.get('ma10', 'N/A')}  MA20={feat.get('ma20', 'N/A')}  MA60={feat.get('ma60', 'N/A')}
RSI(14)={feat.get('rsi14', 'N/A')}
MACD: DIF={feat.get('macd_dif', 'N/A')}  DEA={feat.get('macd_dea', 'N/A')}  柱={feat.get('macd_hist', 'N/A')}
KDJ: K={feat.get('kdj_k', 'N/A')}  D={feat.get('kdj_d', 'N/A')}  J={feat.get('kdj_j', 'N/A')}
布林带: 下轨={feat.get('bb_lower', 'N/A')}  中轨={feat.get('bb_mid', 'N/A')}  上轨={feat.get('bb_upper', 'N/A')}
涨跌幅: 1日={feat.get('ret_1d', 0):+.2f}%  5日={feat.get('ret_5d', 0):+.2f}%  20日={feat.get('ret_20d', 0):+.2f}%  60日={feat.get('ret_60d', 0):+.2f}%
波动率(20日)={feat.get('vol_20d', 'N/A')}%  量比={feat.get('vol_ratio', 'N/A')}x
20日区间: {feat.get('low_20', 'N/A')} ~ {feat.get('high_20', 'N/A')}（当前在{feat.get('pos_in_20d', 'N/A')}%位置）
60日区间: {feat.get('low_60', 'N/A')} ~ {feat.get('high_60', 'N/A')}（当前在{feat.get('pos_in_60d', 'N/A')}%位置）
趋势: {pattern.get('trend_20d', 'N/A')}  站上MA20: {pattern.get('above_ma20', 'N/A')}

【识别形态】
{patterns_text}
【支撑/阻力位】
支撑位: {sr.get('support_levels', 'N/A')}
阻力位: {sr.get('resistance_levels', 'N/A')}
距最近支撑: {sr.get('distance_to_support_pct', 'N/A')}%
距最近阻力: {sr.get('distance_to_resistance_pct', 'N/A')}%

═══════════════════════════════════════
【近10日K线】
{recent_bars_text}
═══════════════════════════════════════
【近期新闻】
{news_text}
【新闻情绪】
情绪均值: {sent.get('avg_sentiment', 'N/A')}（{sent.get('sentiment_label', 'N/A')}）
负面事件: {sent.get('negative_events_count', 0)}条
═══════════════════════════════════════

请基于以上全部数据，以顶级卖方分析师的专业水准，输出以下 JSON 格式的深度分析报告（**必须包含所有字段，不能省略任何一个**）：

{{
  "action": "BUY或SELL或HOLD或WATCH",
  "confidence": 0到100的整数,
  "current_price": {price:.2f},
  "risk_level": "低或中或高",
  "time_horizon": "短线(1-5日)或中线(1-4周)或长线(1-3月)",

  "core_conclusion": {{
    "one_sentence": "一句话结论（30字内，直击要害）",
    "time_sensitivity": "时效性说明（如 '今日盘中可介入' / '观望1-2日等回踩MA20'）",
    "position_advice": {{
      "no_position": "无持仓者：具体到价位的建议（如 '5.10-5.15区间分批建仓30%，跌破4.95止损'）",
      "has_position": "有持仓者：具体建议（如 '持有，跌破4.95减半仓，反弹至5.50止盈一半'）"
    }}
  }},

  "battle_plan": {{
    "ideal_buy": "理想买点+触发条件（如 '5.05-5.10，回踩MA20不破'）",
    "secondary_buy": "次要买点（如 '4.95-5.00，跌破MA20后企稳'）",
    "stop_loss": "止损价+触发条件（如 '4.90，跌破前低+MA60'）",
    "take_profit": "止盈目标+触发条件（如 '5.50（短线）/ 5.80（中线）'）",
    "suggested_position": "建议仓位百分比（如 '20-30%' 或 '不超过50%'）",
    "entry_plan": "建仓计划（如 '分3批：5.10/5.05/5.00各1/3'）",
    "risk_control": "风控要点（如 '严格止损，单股不超过总仓位20%'）"
  }},

  "action_checklist": [
    "执行前检查项1（如 '确认大盘当日未跌破3000点'）",
    "执行前检查项2（如 '确认成交量较前一日放大30%以上'）",
    "执行前检查项3",
    "执行前检查项4",
    "执行前检查项5"
  ],

  "data_perspective": {{
    "trend_status": {{
      "ma_alignment": "均线排列描述（如 'MA5<MA10<MA20<MA60，空头排列'）",
      "is_bullish": false,
      "trend_score": 35,
      "trend_desc": "趋势强度说明"
    }},
    "price_position": {{
      "current_price": {price:.2f},
      "ma5": MA5数值, "ma10": MA10数值, "ma20": MA20数值, "ma60": MA60数值,
      "bias_ma5": MA5乖离率,
      "bias_ma20": MA20乖离率,
      "bias_status": "正常或偏离过大或偏离合理",
      "support_level": 关键支撑位数值,
      "resistance_level": 关键阻力位数值
    }},
    "volume_analysis": {{
      "volume_ratio": 量比数值,
      "volume_status": "放量或缩量或正常",
      "volume_meaning": "成交量含义解读（30字内）"
    }},
    "rsi_status": "超买/超卖/中性 + 数值",
    "macd_status": "金叉/死叉/多头/空头 + 描述"
  }},

  "intelligence": {{
    "sentiment_summary": "市场情绪一句话总结",
    "earnings_outlook": "业绩预期/基本面评估",
    "risk_alerts": ["风险点1（含具体数据）", "风险点2", "风险点3"],
    "positive_catalysts": ["利好1", "利好2", "利好3"],
    "latest_news": "最新值得关注的消息"
  }},

  "summary": "200字以内综合结论",
  "technical_analysis": "详细技术面分析150字+",
  "news_analysis": "消息面分析100字+",
  "market_analysis": "大盘环境分析80字+",
  "risk_analysis": "风险提示80字+",
  "key_points": ["核心要点1（含数据）", "核心要点2", "核心要点3", "核心要点4", "核心要点5"],
  "catalysts": ["潜在催化剂1", "潜在催化剂2", "潜在催化剂3"],
  "risk_factors": ["风险因素1", "风险因素2", "风险因素3"],

  "buy_price_low": 建议买入价下限,
  "buy_price_high": 建议买入价上限,
  "stop_loss": 止损价,
  "take_profit": 止盈目标价,

  "support_levels": [支撑位1, 支撑位2, 支撑位3],
  "resistance_levels": [压力位1, 压力位2, 压力位3],
  "patterns_detected": ["识别到的形态1", "形态2"]
}}

**重要提示：**
- 必须输出完整 JSON，包含所有字段（尤其是 core_conclusion、battle_plan、action_checklist、data_perspective、intelligence）
- core_conclusion.position_advice 必须分别给出无持仓和有持仓的具体建议
- battle_plan 的价格描述要具体到小数点后两位
- action_checklist 必须有 5-8 个实操化的检查项
- 严禁输出 markdown 代码块外的任何文字

**关于 action 的最终决策（重要）：**
- 看到任意 3 条多头信号（多头排列 / 站上 MA20 / MACD 多头 / 量价配合 / 突破 / 健康位置 / 大盘配合）→ 给 BUY
- 看到 2 条以上空头信号（MACD 死叉+破 MA20 / RSI>80 顶背离 / 放量下跌 / 重大利空）→ 给 SELL
- 已经持仓且趋势未坏 → 给 HOLD（明确告诉用户持有理由和何时减仓）
- WATCH 仅在数据严重缺失或多空打架时使用，不要拿 WATCH 当万能挡箭牌
- 客户找你是为了赚钱，不是只想听"观望"。看到机会就给 BUY，看到风险就给 SELL，不要怕承担观点。"""

        try:
            raw = self.llm.chat(
                system_prompt=_SYSTEM,
                user_prompt=user_prompt,
            )
            log.info("LLM raw response length: %d", len(raw or ""))
            log.info("LLM raw response[:500]: %s", (raw or "")[:500])
            if not raw:
                raise ValueError("LLM 返回空响应")

            # 检测 LLM 客户端错误（如余额不足/限流/超时）
            if raw.startswith("[LLM error:") or raw.startswith("[LLM 错误"):
                raise ValueError(f"LLM 调用失败: {raw[:200]}")

            result = self._parse_llm_final(raw)
            if not result:
                raise ValueError("JSON 解析失败")

            # 检测解析后是兜底的 WATCH/raw_response 模式（说明 JSON 解析没成功）
            if result.get("raw_response") and not result.get("core_conclusion"):
                raise ValueError(f"LLM 输出非 JSON 格式: {raw[:200]}")

            result.setdefault("symbol", symbol)
            result.setdefault("name", quote.get("name", symbol))
            result.setdefault("current_price", price)
            result["llm_powered"] = True
            result.setdefault("indicators", feat)

            run.steps.append(AgentStep(
                step=len(run.steps), role="final", content=result
            ))
            return result

        except Exception as exc:
            log.warning("LLM synthesize failed: %s, falling back to rules", exc)
            return _summarize_by_rules(goal, observations)

    # ------------------------------------------------------------------
    # JSON 解析
    # ------------------------------------------------------------------

    def _parse_llm_final(self, content: str) -> dict | None:
        """支持纯JSON、markdown代码块、正文嵌入三种格式。"""
        if not content:
            return None
        text = content.strip()

        # 1. markdown 代码块
        md_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if md_match:
            try:
                data = json.loads(md_match.group(1))
                if isinstance(data, dict):
                    return _normalize_report(data)
            except json.JSONDecodeError:
                pass

        # 2. 纯 JSON
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return _normalize_report(data)
        except json.JSONDecodeError:
            pass

        # 3. 正文嵌入（提取最外层 {...}）
        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            try:
                data = json.loads(brace_match.group(0))
                if isinstance(data, dict):
                    return _normalize_report(data)
            except json.JSONDecodeError:
                pass

        log.warning("super_analyst: could not parse LLM JSON")
        return {
            "action": "WATCH",
            "confidence": 30,
            "summary": text[:500],
            "raw_response": text,
        }


# ---------------------------------------------------------------------------
# 规则引擎（无 LLM 时）
# ---------------------------------------------------------------------------

def _summarize_by_rules(goal: str, observations: list[ToolResult]) -> dict:
    """从工具结果用规则引擎生成完整报告（无 LLM 时的兜底方案）。

    7维信号评分：趋势 / 均线 / RSI / MACD / 量比 / 形态 / 情绪
    净信号数决定 BUY / SELL / HOLD / WATCH
    """
    # ---- 提取股票代码 ----
    symbol = _extract_symbol(goal) or "UNKNOWN"

    # ---- 提取各工具结果 ----
    quote   = _get_obs(observations, "get_realtime_quote")
    feat    = _get_obs(observations, "get_technical_features")
    pattern = _get_obs(observations, "detect_chart_pattern")
    sr      = _get_obs(observations, "get_support_resistance")
    news    = _get_obs(observations, "search_news")
    sent    = _get_obs(observations, "analyze_news_sentiment")

    if feat is None and quote is None:
        return {
            "action": "WATCH",
            "confidence": 0,
            "summary": f"无法获取 {symbol} 的市场数据，请检查数据源连接。",
            "error": "no market data",
        }

    # ---- 基础价格数据 ----
    close      = _safe_float(feat, "current_close") or _safe_float(quote, "last_price") or 0.0
    pct_change = _safe_float(quote, "pct_change") or 0.0
    ma5        = _safe_float(feat, "ma_5d") or 0.0
    ma20       = _safe_float(feat, "ma_20d") or 0.0
    ma60       = _safe_float(feat, "ma_60d") or 0.0
    rsi        = _safe_float(feat, "rsi_14d")
    macd_hist  = _safe_float(feat, "macd_hist")
    vol_ratio  = _safe_float(feat, "volume_ratio_5d") or 1.0
    volatility = _safe_float(feat, "volatility_20d") or 0.02
    ret_5d     = _safe_float(feat, "return_5d") or 0.0
    ret_20d    = _safe_float(feat, "return_20d") or 0.0

    # ---- 形态 ----
    patterns_raw  = (pattern or {}).get("patterns") or []
    pattern_names = [p.get("name", "") for p in patterns_raw if isinstance(p, dict)]
    trend_20d     = (pattern or {}).get("trend_20d") or "unknown"
    above_ma20    = (pattern or {}).get("above_ma20")
    if above_ma20 is None and ma20 > 0:
        above_ma20 = close > ma20

    # ---- 支撑/阻力 ----
    support_levels    = (sr or {}).get("support_levels") or []
    resistance_levels = (sr or {}).get("resistance_levels") or []

    # ---- 情绪 ----
    avg_sent   = _safe_float(sent, "avg_sentiment") or 0.0
    neg_count  = int((sent or {}).get("negative_events_count") or 0)
    news_count = int((news or {}).get("count") or 0)

    # ================================================================
    # 7维信号评分
    # ================================================================
    bull_signals:    list[str] = []
    bear_signals:    list[str] = []
    warning_signals: list[str] = []

    # 1. 趋势
    if trend_20d in ("strong_up", "up"):
        bull_signals.append(f"20日趋势向上（{ret_20d * 100:+.1f}%）")
    elif trend_20d in ("strong_down", "down"):
        bear_signals.append(f"20日趋势向下（{ret_20d * 100:+.1f}%）")

    # 2. 均线位置
    if close > 0 and ma20 > 0:
        gap_ma20 = (close - ma20) / ma20
        if gap_ma20 > 0.03:
            bull_signals.append(f"站上 MA20，偏离 +{gap_ma20 * 100:.1f}%")
        elif gap_ma20 < -0.03:
            bear_signals.append(f"跌破 MA20，偏离 {gap_ma20 * 100:.1f}%")
    if close > 0 and ma60 > 0:
        if close > ma60:
            bull_signals.append(f"站上 MA60（{close:.2f} > {ma60:.2f}）")
        else:
            bear_signals.append(f"跌破 MA60（{close:.2f} < {ma60:.2f}）")

    # 3. RSI
    if rsi is not None:
        if rsi >= 80:
            bear_signals.append(f"RSI {rsi:.0f} 严重超买")
        elif rsi >= 70:
            warning_signals.append(f"RSI {rsi:.0f} 超买区间")
        elif rsi <= 20:
            bull_signals.append(f"RSI {rsi:.0f} 严重超卖，反弹机会")
        elif rsi <= 30:
            bull_signals.append(f"RSI {rsi:.0f} 超卖区间")

    # 4. MACD
    if macd_hist is not None:
        if macd_hist > 0:
            bull_signals.append(f"MACD 柱 {macd_hist:.3f} 在零轴上方")
        else:
            bear_signals.append(f"MACD 柱 {macd_hist:.3f} 在零轴下方")

    # 5. 量比
    if vol_ratio >= 2.0 and ret_5d > 0:
        bull_signals.append(f"放量上涨（量比 {vol_ratio:.1f}×）")
    elif vol_ratio >= 2.0 and ret_5d < 0:
        bear_signals.append(f"放量下跌（量比 {vol_ratio:.1f}×）")
    elif vol_ratio <= 0.5:
        warning_signals.append(f"成交量大幅萎缩（量比 {vol_ratio:.1f}×）")

    # 6. K线形态
    _PATTERN_MAP: dict[str, tuple[str, str]] = {
        "golden_cross":            ("bull", "MA5 金叉 MA20"),
        "death_cross":             ("bear", "MA5 死叉 MA20"),
        "breakout_high":           ("bull", "突破 20 日高点"),
        "breakdown_low":           ("bear", "跌破 20 日低点"),
        "volume_surge":            ("warn", "成交量异常放大"),
        "volume_dry_up":           ("warn", "成交量持续萎缩"),
        "rsi_bearish_divergence":  ("bear", "RSI 顶背离预警"),
        "macd_weakening":          ("warn", "MACD 柱连续萎缩"),
        "volume_price_divergence": ("warn", "量价背离（价涨量缩）"),
        "approaching_resistance":  ("warn", "逼近阻力位"),
        "distribution_zone":       ("bear", "高位筹码派发特征"),
    }
    for pname in pattern_names:
        if pname in _PATTERN_MAP:
            kind, desc = _PATTERN_MAP[pname]
            if kind == "bull":
                bull_signals.append(desc)
            elif kind == "bear":
                bear_signals.append(desc)
            else:
                warning_signals.append(desc)

    # 7. 情绪
    if avg_sent > 0.3:
        bull_signals.append(f"近期新闻情绪偏正面（avg={avg_sent:.2f}）")
    elif avg_sent < -0.3:
        bear_signals.append(
            f"近期新闻情绪偏负面（avg={avg_sent:.2f}，负面事件 {neg_count} 条）"
        )
    elif neg_count >= 3:
        warning_signals.append(f"存在 {neg_count} 条负面新闻事件")

    # ================================================================
    # 综合决策（与 LLM prompt 决策天平保持一致）
    # ================================================================
    bull_score = len(bull_signals)
    bear_score = len(bear_signals)
    warn_score = len(warning_signals)
    net = bull_score - bear_score - warn_score * 0.5

    # 决策门槛：BUY 需要净多头信号 ≥1，SELL 需要净空头信号 ≥3（更严格，避免动辄看空）
    if net >= 4:
        action     = "BUY"
        confidence = min(85, 55 + int(net * 7))
        risk_level = "低" if volatility < 0.025 else "中"
    elif net >= 1:
        action     = "BUY"
        confidence = min(70, 50 + int(net * 6))
        risk_level = "中"
    elif net <= -4:
        action     = "SELL"
        confidence = min(85, 55 + int(abs(net) * 7))
        risk_level = "高"
    elif net <= -2:
        action     = "SELL"
        confidence = min(65, 45 + int(abs(net) * 6))
        risk_level = "中"
    else:
        # 净信号在 [-2, +1) 之间：默认 HOLD（中性偏稳健），不是 WATCH
        action     = "HOLD"
        confidence = 55
        risk_level = "中"

    # 数据不足时降级为 WATCH
    if feat is None:
        action     = "WATCH"
        confidence = min(confidence, 35)

    # 高波动率提升风险等级
    if volatility >= 0.04:
        risk_level = "高"

    # ================================================================
    # 止损 / 止盈 / 买入区间
    # ================================================================
    nearest_support = (
        max((s for s in support_levels if s < close), default=None)
        if support_levels else None
    )
    nearest_resistance = (
        min((r for r in resistance_levels if r > close), default=None)
        if resistance_levels else None
    )

    if action == "BUY" and close > 0:
        # 推荐回踩 MA5/MA10 区间为买点，比追当前价更安全
        ma5_v = feat.get("ma5") if feat else None
        ma10_v = feat.get("ma10") if feat else None
        candidates = []
        if ma5_v and ma5_v > 0: candidates.append(float(ma5_v))
        if ma10_v and ma10_v > 0: candidates.append(float(ma10_v) * 1.005)
        candidates.append(close * 0.985)
        candidates.append(close * 1.005)
        buy_price_low  = round(min(candidates), 3)
        buy_price_high = round(max([c for c in candidates if c <= close * 1.005]), 3)
        # 兜底
        if buy_price_high - buy_price_low < close * 0.005:
            buy_price_low = round(buy_price_high * 0.99, 3)
        stop_loss      = round(nearest_support * 0.99, 3) if nearest_support else round(close * 0.93, 3)
        take_profit    = round(nearest_resistance * 0.99, 3) if nearest_resistance else round(close * 1.10, 3)
        # 止盈必须高于买入上沿
        if take_profit and take_profit < buy_price_high * 1.03:
            take_profit = round(buy_price_high * 1.08, 3)
    elif action == "SELL" and close > 0:
        buy_price_low  = None
        buy_price_high = None
        stop_loss      = round(nearest_resistance * 1.01, 3) if nearest_resistance else round(close * 1.05, 3)
        take_profit    = round(nearest_support * 1.01, 3) if nearest_support else round(close * 0.92, 3)
    elif action == "HOLD" and close > 0:
        # HOLD：给一个加仓区间和减仓阈值
        ma20_v = feat.get("ma20") if feat else None
        buy_price_low  = round((float(ma20_v) if ma20_v else close) * 0.99, 3)
        buy_price_high = round(close * 1.005, 3)
        stop_loss      = (
            round(nearest_support * 0.99, 3) if nearest_support
            else (round(close * 0.92, 3) if close else None)
        )
        take_profit    = (
            round(nearest_resistance * 0.99, 3) if nearest_resistance
            else (round(close * 1.10, 3) if close else None)
        )
    else:
        buy_price_low  = round(close * 0.97, 3) if close else None
        buy_price_high = round(close * 1.00, 3) if close else None
        stop_loss      = (
            round(nearest_support * 0.99, 3) if nearest_support
            else (round(close * 0.93, 3) if close else None)
        )
        take_profit    = (
            round(nearest_resistance * 0.99, 3) if nearest_resistance
            else (round(close * 1.08, 3) if close else None)
        )

    # ================================================================
    # 时间维度判断
    # ================================================================
    if "golden_cross" in pattern_names or "breakout_high" in pattern_names:
        time_horizon = "短线(1-5日)"
    elif trend_20d in ("strong_up", "up") and above_ma20:
        time_horizon = "中线(1-4周)"
    else:
        time_horizon = "短线(1-5日)"

    # ================================================================
    # 文字报告生成
    # ================================================================

    # 技术面
    tech_parts: list[str] = []
    if close:
        tech_parts.append(f"当前价 {close:.2f}，今日{'+' if pct_change >= 0 else ''}{pct_change:.2f}%。")
    if ma5 and ma20:
        ma60_str = f"{ma60:.2f}" if ma60 else "—"
        tech_parts.append(f"MA5={ma5:.2f}，MA20={ma20:.2f}，MA60={ma60_str}。")
    if rsi is not None:
        tech_parts.append(
            f"RSI14={rsi:.1f}，"
            f"{'超买区间' if rsi > 70 else '超卖区间' if rsi < 30 else '中性区间'}。"
        )
    if macd_hist is not None:
        tech_parts.append(f"MACD 柱={macd_hist:.3f}，{'多头' if macd_hist > 0 else '空头'}动能。")
    tech_parts.append(f"量比={vol_ratio:.1f}×，20日波动率={volatility * 100:.1f}%。")
    if pattern_names:
        tech_parts.append(f"识别形态：{'、'.join(pattern_names[:4])}。")
    if bull_signals:
        tech_parts.append(f"利多信号：{'；'.join(bull_signals[:3])}。")
    if bear_signals:
        tech_parts.append(f"利空信号：{'；'.join(bear_signals[:3])}。")
    technical_analysis = "".join(tech_parts)

    # 消息面
    if sent and not sent.get("error"):
        news_analysis = (
            f"近 7 日共 {news_count} 篇相关报道，情绪均值 {avg_sent:.2f}（"
            f"{'偏正面' if avg_sent > 0.1 else '偏负面' if avg_sent < -0.1 else '中性'}），"
            f"负面事件 {neg_count} 条。"
            + (
                "整体舆情平稳，无重大利空。"
                if neg_count == 0
                else f"需关注 {neg_count} 条负面事件对股价的潜在压制。"
            )
        )
    else:
        news_analysis = (
            "暂无新闻数据（数据库未连接），消息面分析缺失，建议手动核查近期公告与新闻。"
        )

    # 大盘
    market_analysis = (
        f"当前个股技术面{'偏强' if net > 0 else '偏弱' if net < 0 else '中性'}，"
        f"20日趋势为「{trend_20d}」，"
        f"{'站上' if above_ma20 else '跌破'} MA20 均线。"
        f"波动率 {volatility * 100:.1f}%，"
        f"{'属于高波动品种，需控制仓位。' if volatility >= 0.04 else '波动率正常。'}"
    )

    # 风险
    risk_parts: list[str] = []
    if bear_signals:
        risk_parts.append(f"技术面风险：{'；'.join(bear_signals[:2])}")
    if warning_signals:
        risk_parts.append(f"预警信号：{'；'.join(warning_signals[:2])}")
    if neg_count > 0:
        risk_parts.append(f"消息面风险：{neg_count} 条负面事件")
    if volatility >= 0.04:
        risk_parts.append(f"高波动风险（{volatility * 100:.1f}%）")
    if not risk_parts:
        risk_parts.append("当前无明显风险信号，但需持续跟踪市场变化")
    risk_analysis = "；".join(risk_parts) + "。"

    # 综合摘要
    buy_range_str = (
        f"买入区间 {buy_price_low}~{buy_price_high}，"
        if action == "BUY" and buy_price_low
        else ""
    )
    stop_str    = f"止损 {stop_loss}，" if stop_loss else ""
    target_str  = f"目标价 {take_profit}。" if take_profit else ""
    summary = (
        f"【{action}】{symbol} — 置信度 {confidence}%，风险等级「{risk_level}」。"
        f"技术面：{bull_score} 个利多信号 vs {bear_score} 个利空信号，{warn_score} 个预警。"
        f"趋势{trend_20d}，{'站上' if above_ma20 else '跌破'} MA20。"
        f"{'消息面情绪正面，' if avg_sent > 0.1 else '消息面情绪负面，' if avg_sent < -0.1 else ''}"
        f"建议{time_horizon}操作。"
        f"{buy_range_str}{stop_str}{target_str}"
    )

    # 关键要点
    key_points: list[str] = []
    if bull_signals:
        key_points.extend(bull_signals[:2])
    if bear_signals:
        key_points.extend(bear_signals[:2])
    if warning_signals:
        key_points.extend(warning_signals[:1])
    key_points = key_points[:5]
    while len(key_points) < 3:
        key_points.append("数据有限，建议结合基本面进一步研究")

    # 催化剂
    catalysts: list[str] = []
    if "golden_cross" in pattern_names:
        catalysts.append("MA5 金叉 MA20，短期动能转强")
    if "breakout_high" in pattern_names:
        catalysts.append("突破 20 日高点，技术形态转多")
    if avg_sent > 0.2:
        catalysts.append("近期正面新闻情绪，市场关注度提升")
    if vol_ratio >= 1.5 and ret_5d > 0:
        catalysts.append("放量上涨，主力资金介入迹象")
    if not catalysts:
        catalysts.append("等待明确催化剂出现")
    catalysts = catalysts[:3]

    # 风险因素
    risk_factors: list[str] = []
    if "death_cross" in pattern_names:
        risk_factors.append("MA5 死叉 MA20，趋势转弱")
    if "rsi_bearish_divergence" in pattern_names:
        risk_factors.append("RSI 顶背离，动能衰竭预警")
    if neg_count >= 2:
        risk_factors.append(f"存在 {neg_count} 条负面新闻事件")
    if volatility >= 0.04:
        risk_factors.append(f"高波动率（{volatility * 100:.1f}%），价格波动剧烈")
    if not above_ma20:
        risk_factors.append("跌破 MA20，中期趋势偏弱")
    if not risk_factors:
        risk_factors.append("当前无重大风险信号")
    risk_factors = risk_factors[:3]

    # 技术指标字典
    indicators = {
        "close":            close,
        "pct_change":       pct_change,
        "ma5":              ma5,
        "ma20":             ma20,
        "ma60":             ma60,
        "rsi_14d":          rsi,
        "macd_hist":        macd_hist,
        "volume_ratio_5d":  vol_ratio,
        "volatility_20d":   round(volatility, 4),
        "return_5d":        round(ret_5d, 4),
        "return_20d":       round(ret_20d, 4),
    }

    return {
        "method":             "fallback_rule_engine",
        "symbol":             symbol,
        "action":             action,
        "confidence":         confidence,
        "current_price":      close,
        "buy_price_low":      buy_price_low,
        "buy_price_high":     buy_price_high,
        "stop_loss":          stop_loss,
        "take_profit":        take_profit,
        "risk_level":         risk_level,
        "time_horizon":       time_horizon,
        "summary":            summary,
        "technical_analysis": technical_analysis,
        "news_analysis":      news_analysis,
        "market_analysis":    market_analysis,
        "risk_analysis":      risk_analysis,
        "key_points":         key_points,
        "catalysts":          catalysts,
        "risk_factors":       risk_factors,
        "support_levels":     support_levels[:3],
        "resistance_levels":  resistance_levels[:3],
        "patterns_detected":  pattern_names,
        "indicators":         indicators,
        # 调试用
        "bull_signals":       bull_signals,
        "bear_signals":       bear_signals,
        "warning_signals":    warning_signals,
    }


# ---------------------------------------------------------------------------
# 模块级辅助函数
# ---------------------------------------------------------------------------

def _normalize_report(data: dict) -> dict:
    """类型修正和默认值填充，确保报告字段完整。"""
    defaults: dict[str, Any] = {
        "action":             "WATCH",
        "confidence":         50,
        "current_price":      None,
        "buy_price_low":      None,
        "buy_price_high":     None,
        "stop_loss":          None,
        "take_profit":        None,
        "risk_level":         "中",
        "time_horizon":       "短线(1-5日)",
        "summary":            "",
        "technical_analysis": "",
        "news_analysis":      "",
        "market_analysis":    "",
        "risk_analysis":      "",
        "key_points":         [],
        "catalysts":          [],
        "risk_factors":       [],
        "support_levels":     [],
        "resistance_levels":  [],
        "patterns_detected":  [],
        "indicators":         {},
        # 新增的仪表盘字段
        "core_conclusion":    {},
        "battle_plan":        {},
        "action_checklist":   [],
        "data_perspective":   {},
        "intelligence":       {},
    }
    result = {**defaults, **data}

    # confidence 归一化
    try:
        result["confidence"] = max(0, min(100, int(float(result["confidence"]))))
    except (TypeError, ValueError):
        result["confidence"] = 50

    # 价格字段转 float
    for f in ("current_price", "buy_price_low", "buy_price_high", "stop_loss", "take_profit"):
        v = result.get(f)
        if v is not None:
            try:
                result[f] = round(float(v), 3)
            except (TypeError, ValueError):
                result[f] = None

    # 列表字段保证是 list
    for lf in (
        "key_points", "catalysts", "risk_factors",
        "support_levels", "resistance_levels", "patterns_detected",
        "action_checklist",
    ):
        if not isinstance(result.get(lf), list):
            result[lf] = []

    # 字典字段保证是 dict
    for df in ("indicators", "core_conclusion", "battle_plan", "data_perspective", "intelligence"):
        if not isinstance(result.get(df), dict):
            result[df] = {}

    return result


def _get_market_context() -> str:
    """获取上证/深证/创业板三大指数实时行情，返回格式化字符串。"""
    try:
        from apps.api.app.services.market_service import get_realtime_quotes
        indices = get_realtime_quotes(["000001.SH", "399001.SZ", "399006.SZ"])
        name_map = {
            "000001.SH": "上证指数",
            "399001.SZ": "深证成指",
            "399006.SZ": "创业板指",
        }
        if indices:
            return "、".join(
                f"{name_map.get(q['symbol'], q['symbol'])}: "
                f"{q['price']:.2f}（{q['change_pct']:+.2f}%）"
                for q in indices
            )
        return "大盘数据暂不可用"
    except Exception:
        return "大盘数据暂不可用"


def _extract_symbol(text: str) -> str:
    """从任意文本中提取 A 股代码，如 600028.SH。"""
    m = re.search(r"\b(\d{6})\.(SH|SZ|BJ)\b", text or "", re.IGNORECASE)
    return m.group(0).upper() if m else ""


def _get_obs(observations: list[ToolResult], name: str) -> dict | None:
    """从 observations 列表中取指定工具的输出（无错误且为 dict 时）。"""
    for o in observations:
        if o.name == name and o.error is None and isinstance(o.output, dict):
            return o.output
    return None


def _safe_float(d: dict | None, key: str) -> float | None:
    """安全地从字典中取浮点数，失败返回 None。"""
    if d is None:
        return None
    v = d.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
