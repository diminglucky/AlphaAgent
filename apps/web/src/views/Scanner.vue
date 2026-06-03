<template>
  <div class="scanner-page">
    <!-- 顶部 -->
    <div class="page-header">
      <div class="header-left">
        <h2 class="page-title">
          <span class="title-icon">🔥</span>
          AI 潜力股扫描器
        </h2>
        <span class="page-subtitle">
          技术海选 → 基本面+资金面过滤 → AI 终审，输出明日具体可买的标的
        </span>
      </div>
      <div class="header-actions">
        <el-button type="primary" :loading="scanning" @click="runScan(false)">
          <template #icon><span>🔍</span></template>
          {{ scanning ? '扫描中...' : '开始扫描' }}
        </el-button>
        <el-button :loading="scanning" @click="runScan(true)" plain>
          <template #icon><span>🔄</span></template>
          强制刷新
        </el-button>
      </div>
    </div>

    <!-- 策略选择器 -->
    <div class="strategy-card">
      <div class="strategy-header">
        <div class="strategy-title">
          <span>🎯 经典策略</span>
          <span class="strategy-count">
            已选 {{ selectedStrategies.length }} / {{ strategies.length }}
          </span>
        </div>
        <div class="strategy-actions">
          <el-button size="small" plain @click="clearStrategies">全部清除</el-button>
          <el-button size="small" plain @click="selectAllStrategies">全选</el-button>
          <el-tag size="small" type="info" effect="plain">至少命中其一</el-tag>
        </div>
      </div>

      <div v-if="!strategies.length" class="strategy-loading">
        <el-icon class="is-loading"><Loading /></el-icon>
        正在加载策略列表...
      </div>

      <div v-else class="strategy-groups">
        <div
          v-for="group in strategyGroups"
          :key="group.category"
          class="strategy-group"
        >
          <div class="group-title">
            <span class="group-dot"></span>
            {{ group.category }}
            <span class="group-count">{{ group.items.length }}</span>
          </div>
          <div class="strategy-grid">
            <div
              v-for="s in group.items"
              :key="s.name"
              class="strategy-item"
              :class="{ active: selectedStrategies.includes(s.name) }"
              @click="toggleStrategy(s.name)"
            >
              <div class="strategy-check">
                <span v-if="selectedStrategies.includes(s.name)">✓</span>
              </div>
              <div class="strategy-info">
                <div class="strategy-name">{{ s.name }}</div>
                <div class="strategy-desc">{{ s.desc }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 扫描参数（折叠） -->
    <el-collapse v-model="paramsOpen" class="params-collapse">
      <el-collapse-item name="params">
        <template #title>
          <span class="collapse-title">⚙️ 扫描参数</span>
          <span class="collapse-summary">
            top_n={{ params.top_n }} · min_score={{ params.min_score }} · pool={{ params.candidate_pool }}
          </span>
        </template>
        <div class="params-row">
          <div class="param-item">
            <span class="param-label">返回数量</span>
            <el-input-number
              v-model="params.top_n"
              :min="5"
              :max="50"
              :step="5"
              size="small"
              controls-position="right"
            />
          </div>
          <div class="param-item">
            <span class="param-label">最低技术分</span>
            <el-input-number
              v-model="params.min_score"
              :min="0"
              :max="100"
              :step="5"
              size="small"
              controls-position="right"
            />
          </div>
          <div class="param-item">
            <span class="param-label">候选池大小</span>
            <el-input-number
              v-model="params.candidate_pool"
              :min="50"
              :max="300"
              :step="20"
              size="small"
              controls-position="right"
            />
          </div>
          <div class="param-item">
            <span class="param-label">AI 终审数量</span>
            <el-input-number
              v-model="params.llm_top_n"
              :min="3"
              :max="20"
              :step="1"
              size="small"
              controls-position="right"
              :disabled="!params.enable_llm"
            />
          </div>
          <div class="param-item">
            <el-switch v-model="params.enable_fundamental" size="small" />
            <span class="param-label" style="margin-left:6px">基本面过滤</span>
          </div>
          <div class="param-item">
            <el-switch v-model="params.enable_llm" size="small" />
            <span class="param-label" style="margin-left:6px">AI 终审</span>
          </div>
          <div class="param-hint">
            完整三层（推荐）约 3-5 分钟；关掉 AI 终审约 1-2 分钟
          </div>
        </div>
      </el-collapse-item>
    </el-collapse>

    <!-- 进度提示 -->
    <div v-if="scanning" class="scanning-tip">
      <el-icon class="is-loading"><Loading /></el-icon>
      <div class="scanning-content">
        <div class="scanning-title">
          {{ scanStage || '正在扫描全市场（一阶段快速过滤 → 二阶段并行深度分析 → 6 维度评分）' }}
        </div>
        <div v-if="scanStageDetail" class="scanning-stage-detail">{{ scanStageDetail }}</div>
        <div class="scanning-progress">
          <el-progress
            :percentage="Math.min(99, Math.round((elapsedSec / estimateSec) * 100))"
            :stroke-width="6"
            :show-text="false"
            color="#409eff"
          />
          <span class="scanning-elapsed">已耗时 {{ elapsedSec }}s / 预计约 {{ estimateSec }}s</span>
        </div>
      </div>
    </div>

    <!-- 大盘状态 -->
    <div v-if="result?.market_status" class="market-card">
      <div class="market-header">
        <span class="market-title">📊 大盘状态</span>
        <el-tag :type="sentimentTagType(result.market_status.sentiment)" size="small" effect="dark">
          {{ result.market_status.sentiment }}
        </el-tag>
      </div>

      <div class="indices-row">
        <div v-for="idx in result.market_status.indices" :key="idx.symbol" class="index-card">
          <div class="idx-name">{{ idx.name }}</div>
          <div class="idx-price" :class="idx.change_pct >= 0 ? 'up' : 'down'">
            {{ idx.price?.toFixed(2) }}
          </div>
          <div class="idx-pct" :class="idx.change_pct >= 0 ? 'up' : 'down'">
            {{ idx.change_pct >= 0 ? '+' : '' }}{{ idx.change_pct?.toFixed(2) }}%
          </div>
        </div>
        <div class="market-stats">
          <div class="stat-row">
            <span class="stat-label">上涨</span>
            <span class="stat-val up">{{ result.market_status.up }}</span>
            <span class="stat-label">下跌</span>
            <span class="stat-val down">{{ result.market_status.down }}</span>
          </div>
          <div class="stat-row">
            <span class="stat-label">涨停</span>
            <span class="stat-val up">{{ result.market_status.limit_up }}</span>
            <span class="stat-label">跌停</span>
            <span class="stat-val down">{{ result.market_status.limit_down }}</span>
          </div>
          <div class="up-ratio">
            <span class="stat-label">上涨占比</span>
            <el-progress
              :percentage="result.market_status.up_ratio"
              :color="result.market_status.up_ratio > 50 ? '#f56c6c' : '#67c23a'"
              :stroke-width="6"
              :show-text="false"
              style="flex:1"
            />
            <span class="ratio-val">{{ result.market_status.up_ratio }}%</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 热门行业 -->
    <div v-if="result?.hot_industries?.length" class="hot-industries">
      <span class="hot-icon">🔥</span>
      <span class="hot-label">今日热门行业:</span>
      <el-tag
        v-for="(ind, i) in result.hot_industries.slice(0, 8)"
        :key="ind.name"
        size="small"
        :type="ind.change_pct >= 2 ? 'danger' : (ind.change_pct >= 0 ? 'warning' : 'success')"
        effect="dark"
        class="hot-tag"
      >
        #{{ i + 1 }} {{ ind.name }} {{ ind.change_pct >= 0 ? '+' : '' }}{{ ind.change_pct?.toFixed(2) }}%
      </el-tag>
    </div>

    <!-- LLM 状态告警 -->
    <el-alert
      v-if="result?.llm_status === 'all_failed'"
      type="error"
      :closable="false"
      class="llm-status-alert"
    >
      <template #title>
        ⚠️ AI 终审失败：所有 LLM 调用都失败（可能是 API Key 余额不足或网络问题）
      </template>
      <template #default>
        当前结果由「规则引擎兜底」生成，建议在
        <router-link to="/settings" style="color:#f56c6c;text-decoration:underline">设置页</router-link>
        检查 LLM 配置后重新扫描。
      </template>
    </el-alert>
    <el-alert
      v-else-if="result?.llm_status === 'partial'"
      type="warning"
      :closable="false"
      class="llm-status-alert"
    >
      <template #title>
        ⚠️ 部分 AI 调用失败，标记 ⚙️ 的股票为规则引擎兜底（非真实 AI 分析）
      </template>
    </el-alert>

    <!-- 扫描结果统计 -->
    <div v-if="result" class="scan-summary">
      <div class="summary-item">
        <div class="summary-label">全市场</div>
        <div class="summary-value">{{ result.scanned?.toLocaleString() }}</div>
      </div>
      <div class="arrow">→</div>
      <div class="summary-item">
        <div class="summary-label">技术海选</div>
        <div class="summary-value">{{ result.tier1_count ?? result.analyzed }}</div>
      </div>
      <div v-if="result.tier2_count != null" class="arrow">→</div>
      <div v-if="result.tier2_count != null" class="summary-item">
        <div class="summary-label">基本面过滤</div>
        <div class="summary-value">{{ result.tier2_count }}</div>
      </div>
      <div v-if="result.tier3_count != null" class="arrow">→</div>
      <div v-if="result.tier3_count != null" class="summary-item">
        <div class="summary-label">AI 终审</div>
        <div class="summary-value">{{ result.tier3_count }}</div>
      </div>
      <div class="arrow">→</div>
      <div class="summary-item highlight">
        <div class="summary-label">推荐</div>
        <div class="summary-value">{{ result.results?.length || 0 }}</div>
      </div>
      <div class="summary-time">
        <el-tag v-if="result.evolution?.model_version" size="small" type="primary" effect="plain" style="margin-right:6px">
          模型 {{ result.evolution.model_version }}
        </el-tag>
        <el-tag v-if="lastScanAt" size="small" type="warning" effect="plain" style="margin-right:6px">
          📌 {{ fmtSavedAt(lastScanAt) }} 保存
        </el-tag>
        <el-tag size="small" :type="result.cached ? 'success' : 'info'" effect="dark">
          {{ result.cached ? '✓ 缓存命中' : `耗时 ${(result.elapsed_ms / 1000).toFixed(1)}s` }}
        </el-tag>
        <el-button size="small" plain style="margin-left:6px" @click="clearSavedResult">
          清空记录
        </el-button>
      </div>
    </div>

    <!-- 潜力股列表 -->
    <div v-if="result?.results?.length" class="stocks-grid">
      <div
        v-for="(stock, i) in result.results"
        :key="stock.symbol"
        class="stock-card"
        :class="`score-${scoreLevel(stock.score)}`"
        @click="openDetail(stock)"
      >
        <div class="rank-badge" :class="i < 3 ? 'rank-top' : ''">{{ i + 1 }}</div>

        <div class="stock-header">
          <div class="stock-id">
            <div class="stock-name">{{ stock.name }}</div>
            <div class="stock-symbol">{{ stock.symbol }}</div>
          </div>
          <!-- AI 评级标签作为整张卡的核心定调 -->
          <div class="stock-action" v-if="stock.ai_analysis?.action">
            <el-tag
              :type="aiActionTagType(stock.ai_analysis.action)"
              effect="dark"
              size="default"
              style="font-size:14px;padding:4px 12px"
            >
              {{ stock.ai_analysis.used_llm === false ? '⚙️' : '🤖' }}
              {{ aiActionLabel(stock.ai_analysis.action) }}
            </el-tag>
            <div class="action-conf">
              把握度 {{ stock.ai_analysis.confidence }}%
              <span v-if="stock.ai_analysis.used_llm === false" style="color:#e6a23c">（规则引擎）</span>
            </div>
          </div>
        </div>

        <div class="stock-price-row">
          <div class="stock-price">¥{{ stock.price?.toFixed(2) }}</div>
          <div class="stock-pct" :class="stock.change_pct >= 0 ? 'up' : 'down'">
            {{ stock.change_pct >= 0 ? '+' : '' }}{{ stock.change_pct?.toFixed(2) }}%
          </div>
        </div>

        <div v-if="stock.evolution" class="evo-row">
          <div class="evo-pill primary">
            <span>进化模型概率</span>
            <b>{{ stock.evolution.probability_pct }}%</b>
          </div>
          <div class="evo-pill">
            <span>{{ stock.evolution.best_horizon_days }} 日目标</span>
            <b>+{{ stock.evolution.target_return_pct }}%</b>
          </div>
          <div class="evo-pill">
            <span>预期收益</span>
            <b :class="stock.evolution.expected_return_pct >= 0 ? 'up' : 'down'">
              {{ stock.evolution.expected_return_pct >= 0 ? '+' : '' }}{{ stock.evolution.expected_return_pct }}%
            </b>
          </div>
        </div>

        <!-- 4 维独立评分 -->
        <div class="dim-row">
          <div class="dim-cell">
            <div class="dim-cell-label">技术</div>
            <div class="dim-cell-bar">
              <div class="dim-cell-fill" :style="{ width: stock.score + '%', background: dimColor(stock.score, 100) }"></div>
            </div>
            <div class="dim-cell-value">{{ stock.score }}/100</div>
          </div>
          <div class="dim-cell" v-if="(stock.fundamental?.quality ?? null) != null">
            <div class="dim-cell-label">基本面</div>
            <div class="dim-cell-bar">
              <div class="dim-cell-fill" :style="{ width: (stock.fundamental.quality / 25 * 100) + '%', background: dimColor(stock.fundamental.quality, 25) }"></div>
            </div>
            <div class="dim-cell-value">{{ stock.fundamental.quality }}/25</div>
          </div>
          <div class="dim-cell" v-if="(stock.fundamental?.flow_score ?? null) != null">
            <div class="dim-cell-label">资金面</div>
            <div class="dim-cell-bar">
              <div class="dim-cell-fill" :style="{ width: (stock.fundamental.flow_score / 25 * 100) + '%', background: dimColor(stock.fundamental.flow_score, 25) }"></div>
            </div>
            <div class="dim-cell-value">{{ stock.fundamental.flow_score }}/25</div>
          </div>
          <div class="dim-cell" v-if="stock.ai_analysis?.confidence != null">
            <div class="dim-cell-label">AI</div>
            <div class="dim-cell-bar">
              <div class="dim-cell-fill" :style="{ width: stock.ai_analysis.confidence + '%', background: dimColor(stock.ai_analysis.confidence, 100) }"></div>
            </div>
            <div class="dim-cell-value">{{ stock.ai_analysis.confidence }}/100</div>
          </div>
        </div>

        <!-- 雷达图 + 标签 -->
        <div class="card-mid">
          <div class="radar-wrap">
            <v-chart
              class="radar-chart"
              :option="getRadarOption(stock)"
              autoresize
            />
          </div>
          <div class="card-side">
            <!-- 命中策略 -->
            <div v-if="stock.strategies?.length" class="card-strategies">
              <el-tooltip
                v-for="st in stock.strategies"
                :key="st.name"
                :content="st.desc"
                placement="top"
                :show-after="200"
              >
                <el-tag
                  size="small"
                  type="success"
                  effect="dark"
                  class="strategy-tag"
                >
                  {{ st.name }}
                </el-tag>
              </el-tooltip>
            </div>
            <!-- 标签 -->
            <div class="card-tags" v-if="stock.tags?.length">
              <el-tag
                v-for="tag in stock.tags.slice(0, 5)"
                :key="tag"
                size="small"
                :type="tagType(tag)"
                effect="dark"
                class="stock-tag"
              >
                {{ tag }}
              </el-tag>
            </div>
          </div>
        </div>

        <!-- AI 终审结论（如果 LLM 终审过）-->
        <div v-if="stock.ai_analysis && stock.ai_analysis.action" class="ai-verdict" :class="`ai-${(stock.ai_analysis.action || '').toLowerCase()}`">
          <div class="ai-header">
            <span class="ai-icon">🤖</span>
            <span class="ai-title">AI 终审</span>
            <el-tag size="small" :type="aiActionTagType(stock.ai_analysis.action)" effect="dark">
              {{ aiActionLabel(stock.ai_analysis.action) }}
            </el-tag>
            <span class="ai-conf" :style="{ color: confColor(stock.ai_analysis.confidence) }">
              把握度 {{ stock.ai_analysis.confidence }}%
            </span>
          </div>
          <div v-if="stock.ai_analysis.core_conclusion?.one_sentence" class="ai-quote">
            "{{ stock.ai_analysis.core_conclusion.one_sentence }}"
          </div>
        </div>

        <!-- 基本面 + 资金面 关键指标 -->
        <div v-if="stock.fundamental?.info" class="fund-row">
          <span v-if="stock.fundamental.info.pe != null" class="fund-cell">
            PE <b :class="peClass(stock.fundamental.info.pe)">{{ stock.fundamental.info.pe?.toFixed(1) }}</b>
          </span>
          <span v-if="stock.fundamental.info.float_mv" class="fund-cell">
            流通 <b>{{ (stock.fundamental.info.float_mv/1e8).toFixed(0) }}亿</b>
          </span>
          <span v-if="stock.fundamental.info.industry" class="fund-cell industry-cell">
            行业 <b>{{ stock.fundamental.info.industry }}</b>
            <em v-if="stock.fundamental.industry_rank">
              #{{ stock.fundamental.industry_rank.rank }}/{{ stock.fundamental.industry_rank.total }}
            </em>
          </span>
          <span v-if="stock.fundamental.industry_score != null" class="fund-cell">
            景气 <b :class="industryScoreClass(stock.fundamental.industry_score)">
              {{ stock.fundamental.industry_score }}/15
            </b>
          </span>
          <span v-if="stock.fundamental.northbound?.add_mv_5d != null" class="fund-cell">
            北向 <b :class="stock.fundamental.northbound.add_mv_5d>=0?'up':'down'">
              {{ fmtSignedAmt(stock.fundamental.northbound.add_mv_5d) }}
            </b>
          </span>
          <span v-if="stock.fundamental.northbound_score != null" class="fund-cell">
            北向分 <b :class="industryScoreClass(stock.fundamental.northbound_score)">
              {{ stock.fundamental.northbound_score }}/15
            </b>
          </span>
          <span v-if="stock.fundamental.research?.report_count" class="fund-cell">
            研报 <b class="up">{{ stock.fundamental.research.report_count }}篇</b>
          </span>
          <span v-if="stock.fundamental.research_score != null" class="fund-cell">
            研报分 <b :class="industryScoreClass(stock.fundamental.research_score)">
              {{ stock.fundamental.research_score }}/15
            </b>
          </span>
          <span v-if="stock.fundamental.insider_reduction?.reduce_count" class="fund-cell">
            减持 <b class="down">{{ stock.fundamental.insider_reduction.reduce_count }}次</b>
          </span>
          <span v-if="stock.fundamental.insider_reduction_score != null" class="fund-cell">
            减持风险 <b :class="stock.fundamental.insider_reduction_score >= 5 ? 'down' : 'up'">
              {{ stock.fundamental.insider_reduction_score }}/15
            </b>
          </span>
          <span v-if="stock.fundamental.flow?.today_net != null" class="fund-cell">
            主力 <b :class="stock.fundamental.flow.today_net>=0?'up':'down'">
              {{ stock.fundamental.flow.today_net>=0?'+':'' }}{{ (stock.fundamental.flow.today_net/1e8).toFixed(2) }}亿
            </b>
          </span>
          <span v-if="stock.fundamental.flow?.turnover_rate != null" class="fund-cell">
            换手 <b>{{ stock.fundamental.flow.turnover_rate?.toFixed(1) }}%</b>
          </span>
        </div>

        <!-- 明日交易计划（核心） -->
        <div v-if="stock.trade_plan" class="trade-plan" :class="`plan-${ratingClass(stock.trade_plan.rating)}`">
          <div class="plan-header">
            <el-tag size="small" :type="ratingTagType(stock.trade_plan.rating)" effect="dark">
              {{ stock.trade_plan.rating }}
            </el-tag>
            <span class="plan-horizon">{{ stock.trade_plan.holding_days }}</span>
            <span class="plan-pos">仓位 {{ stock.trade_plan.position_pct }}</span>
          </div>
          <div class="plan-prices">
            <div class="pp-cell">
              <div class="pp-label">买入区间</div>
              <div class="pp-val buy">{{ stock.trade_plan.entry_low?.toFixed(2) }} - {{ stock.trade_plan.entry_high?.toFixed(2) }}</div>
            </div>
            <div class="pp-cell">
              <div class="pp-label">止损</div>
              <div class="pp-val stop">{{ stock.trade_plan.stop_loss?.toFixed(2) }}</div>
            </div>
            <div class="pp-cell">
              <div class="pp-label">短目标</div>
              <div class="pp-val tgt">{{ stock.trade_plan.target1?.toFixed(2) }}</div>
            </div>
          </div>
          <div class="plan-rr">
            <span class="rr-item">期望收益 <b class="up">+{{ stock.trade_plan.expected_return_pct }}%</b></span>
            <span class="rr-item">最大回撤 <b class="down">-{{ stock.trade_plan.max_loss_pct }}%</b></span>
            <span class="rr-item">盈亏比 <b>{{ stock.trade_plan.risk_reward }}</b></span>
          </div>
          <div class="plan-tomorrow">📅 {{ stock.trade_plan.tomorrow_plan }}</div>
        </div>

        <!-- Top 3 信号 -->
        <div class="stock-signals" v-if="stock.signals?.length">
          <div v-for="(sig, idx) in stock.signals.slice(0, 3)" :key="idx" class="signal-line">
            <span class="signal-dim-tag" :class="`dim-${sig.dim || 'other'}`">
              {{ dimLabel(sig.dim) }}
            </span>
            <span class="signal-dot" :class="`signal-${sig.strength}`">●</span>
            <span class="signal-desc">{{ sig.desc }}</span>
          </div>
          <div v-if="stock.signals.length > 3" class="signal-more">
            +{{ stock.signals.length - 3 }} 个信号
          </div>
        </div>

        <!-- 操作 -->
        <div class="stock-actions">
          <el-button size="small" type="primary" @click.stop="goAnalyze(stock)">
            🤖 Agent
          </el-button>
          <el-button size="small" @click.stop="addWatchlist(stock)" plain>
            + 自选
          </el-button>
          <el-button size="small" @click.stop="goKline(stock)" plain>
            📉 K线
          </el-button>
          <el-button size="small" type="warning" @click.stop="goTrade(stock)" plain>
            交易
          </el-button>
        </div>
      </div>
    </div>

    <!-- AI 否决的股票（透明度展示）-->
    <div v-if="result?.rejected_results?.length" class="rejected-section">
      <div class="rejected-header" @click="rejectedOpen = !rejectedOpen">
        <span class="rejected-title">
          <el-icon><ArrowRight v-if="!rejectedOpen" /><ArrowDown v-else /></el-icon>
          AI 否决（{{ result.rejected_results.length }} 只）
        </span>
        <span class="rejected-hint">
          这些股票通过了技术海选 + 基本面过滤，但 AI 综合判断后认为不宜买入
        </span>
      </div>
      <div v-if="rejectedOpen" class="rejected-list">
        <div
          v-for="r in result.rejected_results"
          :key="r.symbol"
          class="rejected-item"
          @click="openDetail(r)"
        >
          <div class="rj-id">
            <span class="rj-name">{{ r.name }}</span>
            <span class="rj-symbol">{{ r.symbol }}</span>
          </div>
          <el-tag size="small" :type="aiActionTagType(r.ai_analysis?.action)" effect="plain">
            {{ aiActionLabel(r.ai_analysis?.action) }} {{ r.ai_analysis?.confidence }}%
          </el-tag>
          <span class="rj-reason">{{ r.ai_analysis?.core_conclusion?.one_sentence || r.ai_analysis?.rejected_reason }}</span>
        </div>
      </div>
    </div>

    <div v-if="result && !result.results?.length && !result.rejected_results?.length" class="empty-state">
      <div class="empty-icon">😶</div>
      <div class="empty-text">未找到符合条件的潜力股，可降低「最低分数」或减少策略限制再试</div>
    </div>

    <div v-if="!result && !scanning" class="empty-state">
      <div class="empty-icon">🔥</div>
      <div class="empty-text">点击「开始扫描」从全市场识别有上涨潜力的股票</div>
      <div class="scan-explain">
        <p><b>6 维度评分系统（满分 100）</b></p>
        <div class="dim-cards">
          <div class="dim-card"><span class="dim-icon">📈</span><b>趋势</b> <span class="dim-max">/20</span></div>
          <div class="dim-card"><span class="dim-icon">⚡</span><b>动量</b> <span class="dim-max">/15</span></div>
          <div class="dim-card"><span class="dim-icon">📊</span><b>量能</b> <span class="dim-max">/20</span></div>
          <div class="dim-card"><span class="dim-icon">🔷</span><b>形态</b> <span class="dim-max">/15</span></div>
          <div class="dim-card"><span class="dim-icon">💰</span><b>资金</b> <span class="dim-max">/15</span></div>
          <div class="dim-card"><span class="dim-icon">🎯</span><b>综合</b> <span class="dim-max">/15</span></div>
        </div>
        <p style="margin-top: 12px"><b>11 种经典策略</b></p>
        <div class="tag-cloud">
          <el-tag v-for="s in strategies" :key="s.name" size="small" effect="dark">
            {{ s.name }}
          </el-tag>
        </div>
      </div>
    </div>

    <!-- 详情抽屉 -->
    <el-drawer
      v-model="drawerVisible"
      :title="`${detailStock?.name} (${detailStock?.symbol}) — 详情`"
      direction="rtl"
      size="560px"
    >
      <div v-if="detailStock" class="drawer-content">
        <!-- AI 终审结论作为标题（如果有）-->
        <div v-if="detailStock.ai_analysis?.action" class="drawer-ai-card" :class="`ai-${(detailStock.ai_analysis.action || '').toLowerCase()}`">
          <div class="dac-header">
            <el-tag :type="aiActionTagType(detailStock.ai_analysis.action)" effect="dark" size="large">
              🤖 AI {{ aiActionLabel(detailStock.ai_analysis.action) }}
            </el-tag>
            <span class="dac-conf">把握度 {{ detailStock.ai_analysis.confidence }}%</span>
          </div>
          <div v-if="detailStock.ai_analysis.core_conclusion?.one_sentence" class="dac-quote">
            "{{ detailStock.ai_analysis.core_conclusion.one_sentence }}"
          </div>
          <div v-if="detailStock.ai_analysis.core_conclusion?.position_advice" class="dac-advice">
            <div v-if="detailStock.ai_analysis.core_conclusion.position_advice.no_position" class="advice-line">
              <span class="advice-label">无持仓:</span>
              <span>{{ detailStock.ai_analysis.core_conclusion.position_advice.no_position }}</span>
            </div>
            <div v-if="detailStock.ai_analysis.core_conclusion.position_advice.has_position" class="advice-line">
              <span class="advice-label">有持仓:</span>
              <span>{{ detailStock.ai_analysis.core_conclusion.position_advice.has_position }}</span>
            </div>
          </div>
        </div>

        <!-- 4 维独立评分卡 -->
        <div class="drawer-multi-score">
          <div class="dms-cell">
            <div class="dms-label">技术分</div>
            <div class="dms-value" :style="{ color: dimColor(detailStock.score, 100) }">{{ detailStock.score }}</div>
            <div class="dms-max">/ 100</div>
          </div>
          <div class="dms-cell" v-if="(detailStock.fundamental?.quality ?? null) != null">
            <div class="dms-label">基本面</div>
            <div class="dms-value" :style="{ color: dimColor(detailStock.fundamental.quality, 25) }">{{ detailStock.fundamental.quality }}</div>
            <div class="dms-max">/ 25</div>
          </div>
          <div class="dms-cell" v-if="(detailStock.fundamental?.flow_score ?? null) != null">
            <div class="dms-label">资金面</div>
            <div class="dms-value" :style="{ color: dimColor(detailStock.fundamental.flow_score, 25) }">{{ detailStock.fundamental.flow_score }}</div>
            <div class="dms-max">/ 25</div>
          </div>
          <div class="dms-cell" v-if="(detailStock.fundamental?.industry_score ?? null) != null">
            <div class="dms-label">行业景气</div>
            <div class="dms-value" :style="{ color: dimColor(detailStock.fundamental.industry_score, 15) }">{{ detailStock.fundamental.industry_score }}</div>
            <div class="dms-max">/ 15</div>
          </div>
          <div class="dms-cell" v-if="(detailStock.fundamental?.northbound_score ?? null) != null">
            <div class="dms-label">北向资金</div>
            <div class="dms-value" :style="{ color: dimColor(detailStock.fundamental.northbound_score, 15) }">{{ detailStock.fundamental.northbound_score }}</div>
            <div class="dms-max">/ 15</div>
          </div>
          <div class="dms-cell" v-if="(detailStock.fundamental?.research_score ?? null) != null">
            <div class="dms-label">机构研报</div>
            <div class="dms-value" :style="{ color: dimColor(detailStock.fundamental.research_score, 15) }">{{ detailStock.fundamental.research_score }}</div>
            <div class="dms-max">/ 15</div>
          </div>
          <div class="dms-cell" v-if="(detailStock.fundamental?.insider_reduction_score ?? null) != null">
            <div class="dms-label">减持风险</div>
            <div class="dms-value" :style="{ color: riskColor(detailStock.fundamental.insider_reduction_score, 15) }">{{ detailStock.fundamental.insider_reduction_score }}</div>
            <div class="dms-max">/ 15</div>
          </div>
          <div class="dms-cell" v-if="detailStock.ai_analysis?.confidence != null">
            <div class="dms-label">AI 把握</div>
            <div class="dms-value" :style="{ color: dimColor(detailStock.ai_analysis.confidence, 100) }">{{ detailStock.ai_analysis.confidence }}</div>
            <div class="dms-max">/ 100</div>
          </div>
        </div>

        <div v-if="detailStock.evolution" class="drawer-section evolution-detail">
          <div class="drawer-section-title">🧬 模型进化预测</div>
          <div class="evo-big-grid">
            <div class="evo-big-cell">
              <div class="evo-big-label">最佳周期</div>
              <div class="evo-big-value">{{ detailStock.evolution.best_horizon_days }} 日</div>
            </div>
            <div class="evo-big-cell">
              <div class="evo-big-label">上涨概率</div>
              <div class="evo-big-value up">{{ detailStock.evolution.probability_pct }}%</div>
            </div>
            <div class="evo-big-cell">
              <div class="evo-big-label">目标涨幅</div>
              <div class="evo-big-value">+{{ detailStock.evolution.target_return_pct }}%</div>
            </div>
            <div class="evo-big-cell">
              <div class="evo-big-label">预期收益</div>
              <div class="evo-big-value" :class="detailStock.evolution.expected_return_pct >= 0 ? 'up' : 'down'">
                {{ detailStock.evolution.expected_return_pct >= 0 ? '+' : '' }}{{ detailStock.evolution.expected_return_pct }}%
              </div>
            </div>
          </div>
          <div v-if="detailStock.evolution.probabilities_by_horizon?.length" class="evo-horizons">
            <div
              v-for="h in detailStock.evolution.probabilities_by_horizon"
              :key="h.horizon_days"
              class="evo-horizon"
            >
              <span>{{ h.horizon_days }} 日</span>
              <b>{{ h.probability_pct }}%</b>
            </div>
          </div>
        </div>

        <div class="drawer-section drawer-meta">
          <span>¥{{ detailStock.price?.toFixed(2) }}</span>
          <span :class="detailStock.change_pct >= 0 ? 'up' : 'down'">
            {{ detailStock.change_pct >= 0 ? '+' : '' }}{{ detailStock.change_pct?.toFixed(2) }}%
          </span>
          <span>成交额 {{ fmtAmt(detailStock.turnover) }}</span>
        </div>

        <!-- 行业景气详情 -->
        <div v-if="detailStock.fundamental?.info?.industry || detailStock.fundamental?.industry_rank" class="drawer-section industry-detail">
          <div class="drawer-section-title">🏭 行业景气</div>
          <div class="industry-grid">
            <div class="industry-cell-big">
              <span>所属行业</span>
              <b>{{ detailStock.fundamental?.info?.industry || '未知' }}</b>
            </div>
            <div v-if="detailStock.fundamental?.industry_rank" class="industry-cell-big">
              <span>行业排名</span>
              <b>#{{ detailStock.fundamental.industry_rank.rank }}/{{ detailStock.fundamental.industry_rank.total }}</b>
            </div>
            <div v-if="detailStock.fundamental?.industry_rank" class="industry-cell-big">
              <span>行业涨跌</span>
              <b :class="detailStock.fundamental.industry_rank.change_pct >= 0 ? 'up' : 'down'">
                {{ fmtSignedPct(detailStock.fundamental.industry_rank.change_pct) }}
              </b>
            </div>
            <div v-if="detailStock.fundamental?.industry_rank?.net_inflow != null" class="industry-cell-big">
              <span>行业净流入</span>
              <b :class="detailStock.fundamental.industry_rank.net_inflow >= 0 ? 'up' : 'down'">
                {{ fmtSignedAmt(detailStock.fundamental.industry_rank.net_inflow) }}
              </b>
            </div>
          </div>
          <div v-if="detailStock.fundamental?.industry_items?.length" class="fund-items industry-items">
            <div
              v-for="(item, i) in detailStock.fundamental.industry_items"
              :key="'ind'+i"
              class="fund-item"
              :class="`fi-${item.kind}`"
            >
              <span class="fi-score">{{ item.score >= 0 ? '+' : '' }}{{ item.score }}</span>
              <span class="fi-desc">{{ item.desc }}</span>
            </div>
          </div>
        </div>

        <!-- 基本面详情 -->
        <div v-if="detailStock.fundamental?.quality_items?.length" class="drawer-section">
          <div class="drawer-section-title">💎 基本面分析</div>
          <div class="fund-items">
            <div
              v-for="(item, i) in detailStock.fundamental.quality_items"
              :key="'q'+i"
              class="fund-item"
              :class="`fi-${item.kind}`"
            >
              <span class="fi-score">{{ item.score >= 0 ? '+' : '' }}{{ item.score }}</span>
              <span class="fi-desc">{{ item.desc }}</span>
            </div>
          </div>
        </div>

        <!-- 资金面详情 -->
        <div v-if="detailStock.fundamental?.flow_items?.length" class="drawer-section">
          <div class="drawer-section-title">💰 资金面分析</div>
          <div class="fund-items">
            <div
              v-for="(item, i) in detailStock.fundamental.flow_items"
              :key="'f'+i"
              class="fund-item"
              :class="`fi-${item.kind}`"
            >
              <span class="fi-score">{{ item.score >= 0 ? '+' : '' }}{{ item.score }}</span>
              <span class="fi-desc">{{ item.desc }}</span>
            </div>
          </div>
        </div>

        <!-- 北向资金详情 -->
        <div v-if="detailStock.fundamental?.northbound || detailStock.fundamental?.northbound_items?.length" class="drawer-section northbound-detail">
          <div class="drawer-section-title">🧭 北向资金</div>
          <div v-if="detailStock.fundamental?.northbound" class="industry-grid">
            <div class="industry-cell-big">
              <span>5日增持市值</span>
              <b :class="detailStock.fundamental.northbound.add_mv_5d >= 0 ? 'up' : 'down'">
                {{ fmtSignedAmt(detailStock.fundamental.northbound.add_mv_5d) }}
              </b>
            </div>
            <div class="industry-cell-big">
              <span>5日市值增幅</span>
              <b :class="detailStock.fundamental.northbound.add_mv_pct_5d >= 0 ? 'up' : 'down'">
                {{ fmtSignedPct(detailStock.fundamental.northbound.add_mv_pct_5d) }}
              </b>
            </div>
            <div class="industry-cell-big">
              <span>占流通股变化</span>
              <b :class="detailStock.fundamental.northbound.add_ratio_float_5d >= 0 ? 'up' : 'down'">
                {{ fmtSignedPct(detailStock.fundamental.northbound.add_ratio_float_5d) }}
              </b>
            </div>
            <div class="industry-cell-big">
              <span>当前持股市值</span>
              <b>{{ fmtAmt(detailStock.fundamental.northbound.hold_mv) }}</b>
            </div>
          </div>
          <div v-if="detailStock.fundamental?.northbound_items?.length" class="fund-items industry-items">
            <div
              v-for="(item, i) in detailStock.fundamental.northbound_items"
              :key="'nb'+i"
              class="fund-item"
              :class="`fi-${item.kind}`"
            >
              <span class="fi-score">{{ item.score >= 0 ? '+' : '' }}{{ item.score }}</span>
              <span class="fi-desc">{{ item.desc }}</span>
            </div>
          </div>
        </div>

        <!-- 机构研报详情 -->
        <div v-if="detailStock.fundamental?.research || detailStock.fundamental?.research_items?.length" class="drawer-section research-detail">
          <div class="drawer-section-title">📚 机构研报</div>
          <div v-if="detailStock.fundamental?.research" class="industry-grid">
            <div class="industry-cell-big">
              <span>近30天研报</span>
              <b>{{ detailStock.fundamental.research.report_count || 0 }} 篇</b>
            </div>
            <div class="industry-cell-big">
              <span>买入评级</span>
              <b class="up">{{ detailStock.fundamental.research.buy_count || 0 }} 篇</b>
            </div>
            <div class="industry-cell-big">
              <span>正面评级</span>
              <b class="up">{{ detailStock.fundamental.research.positive_count || 0 }} 篇</b>
            </div>
            <div class="industry-cell-big">
              <span>覆盖机构</span>
              <b>{{ detailStock.fundamental.research.institutions?.length || 0 }} 家</b>
            </div>
          </div>
          <div v-if="detailStock.fundamental?.research_items?.length" class="fund-items industry-items">
            <div
              v-for="(item, i) in detailStock.fundamental.research_items"
              :key="'rs'+i"
              class="fund-item"
              :class="`fi-${item.kind}`"
            >
              <span class="fi-score">{{ item.score >= 0 ? '+' : '' }}{{ item.score }}</span>
              <span class="fi-desc">{{ item.desc }}</span>
            </div>
          </div>
          <div v-if="detailStock.fundamental?.research?.latest_reports?.length" class="research-list">
            <div
              v-for="(report, i) in detailStock.fundamental.research.latest_reports"
              :key="'report'+i"
              class="research-item"
            >
              <span class="research-date">{{ report.date }}</span>
              <span class="research-rating">{{ report.rating || '未评级' }}</span>
              <span class="research-title">{{ report.title }}</span>
              <span class="research-org">{{ report.institution }}</span>
            </div>
          </div>
        </div>

        <!-- 减持风险详情 -->
        <div v-if="detailStock.fundamental?.insider_reduction || detailStock.fundamental?.insider_reduction_items?.length" class="drawer-section reduction-detail">
          <div class="drawer-section-title">⚠️ 减持风险</div>
          <div v-if="detailStock.fundamental?.insider_reduction" class="industry-grid">
            <div class="industry-cell-big">
              <span>近90天减持</span>
              <b :class="detailStock.fundamental.insider_reduction.reduce_count ? 'down' : 'up'">
                {{ detailStock.fundamental.insider_reduction.reduce_count || 0 }} 次
              </b>
            </div>
            <div class="industry-cell-big">
              <span>估算金额</span>
              <b :class="detailStock.fundamental.insider_reduction.total_reduce_amount ? 'down' : 'up'">
                {{ fmtAmt(detailStock.fundamental.insider_reduction.total_reduce_amount) }}
              </b>
            </div>
            <div class="industry-cell-big">
              <span>估算股数</span>
              <b>{{ fmtShares(detailStock.fundamental.insider_reduction.total_reduce_shares) }}</b>
            </div>
            <div class="industry-cell-big">
              <span>最近日期</span>
              <b>{{ detailStock.fundamental.insider_reduction.latest_date || '无' }}</b>
            </div>
          </div>
          <div v-if="detailStock.fundamental?.insider_reduction_items?.length" class="fund-items industry-items">
            <div
              v-for="(item, i) in detailStock.fundamental.insider_reduction_items"
              :key="'rd'+i"
              class="fund-item"
              :class="`fi-${item.kind}`"
            >
              <span class="fi-score">{{ item.score }}</span>
              <span class="fi-desc">{{ item.desc }}</span>
            </div>
          </div>
          <div v-if="detailStock.fundamental?.insider_reduction?.events?.length" class="research-list">
            <div
              v-for="(event, i) in detailStock.fundamental.insider_reduction.events"
              :key="'reduce'+i"
              class="research-item reduction-item"
            >
              <span class="research-date">{{ event.date }}</span>
              <span class="research-rating">{{ event.person || '相关方' }}</span>
              <span class="research-title">{{ event.reason || event.relation || '股份变动' }}</span>
              <span class="research-org down">{{ fmtSignedAmt(event.amount) }}</span>
            </div>
          </div>
        </div>

        <!-- AI 看好理由 / 风险 -->
        <div v-if="detailStock.ai_analysis?.key_points?.length" class="drawer-section">
          <div class="drawer-section-title">🎯 AI 核心观点</div>
          <ul class="ai-points">
            <li v-for="(p, i) in detailStock.ai_analysis.key_points" :key="'kp'+i">{{ p }}</li>
          </ul>
          <div v-if="detailStock.ai_analysis.catalysts?.length" style="margin-top:8px">
            <div class="ap-sub-title up">✓ 催化剂</div>
            <ul class="ai-points">
              <li v-for="(p, i) in detailStock.ai_analysis.catalysts" :key="'cat'+i">{{ p }}</li>
            </ul>
          </div>
          <div v-if="detailStock.ai_analysis.risk_factors?.length" style="margin-top:8px">
            <div class="ap-sub-title down">⚠ 风险</div>
            <ul class="ai-points">
              <li v-for="(p, i) in detailStock.ai_analysis.risk_factors" :key="'rf'+i">{{ p }}</li>
            </ul>
          </div>
        </div>

        <!-- 明日交易计划（详细版） -->
        <div v-if="detailStock.trade_plan" class="drawer-section drawer-plan" :class="`plan-${ratingClass(detailStock.trade_plan.rating)}`">
          <div class="drawer-section-title">
            📅 明日交易计划
            <el-tag size="small" :type="ratingTagType(detailStock.trade_plan.rating)" effect="dark" style="margin-left:6px">
              {{ detailStock.trade_plan.rating }}
            </el-tag>
          </div>
          <div class="plan-tomorrow-big">{{ detailStock.trade_plan.tomorrow_plan }}</div>
          <div class="plan-grid">
            <div class="plan-cell">
              <div class="pc-label">买入区间</div>
              <div class="pc-value buy">¥{{ detailStock.trade_plan.entry_low?.toFixed(2) }} ~ ¥{{ detailStock.trade_plan.entry_high?.toFixed(2) }}</div>
              <div class="pc-sub">中位 ¥{{ detailStock.trade_plan.entry_mid?.toFixed(2) }}</div>
            </div>
            <div class="plan-cell">
              <div class="pc-label">止损位</div>
              <div class="pc-value stop">¥{{ detailStock.trade_plan.stop_loss?.toFixed(2) }}</div>
              <div class="pc-sub down">最大回撤 -{{ detailStock.trade_plan.max_loss_pct }}%</div>
            </div>
            <div class="plan-cell">
              <div class="pc-label">短线目标（5-10日）</div>
              <div class="pc-value tgt">¥{{ detailStock.trade_plan.target1?.toFixed(2) }}</div>
              <div class="pc-sub up">期望 +{{ detailStock.trade_plan.expected_return_pct }}%</div>
            </div>
            <div class="plan-cell">
              <div class="pc-label">中线目标（20-30日）</div>
              <div class="pc-value tgt">¥{{ detailStock.trade_plan.target2?.toFixed(2) }}</div>
              <div class="pc-sub">{{ detailStock.trade_plan.holding_days }}</div>
            </div>
            <div class="plan-cell">
              <div class="pc-label">建议仓位</div>
              <div class="pc-value">{{ detailStock.trade_plan.position_pct }}</div>
              <div class="pc-sub">{{ detailStock.trade_plan.time_horizon }}</div>
            </div>
            <div class="plan-cell">
              <div class="pc-label">风险收益比</div>
              <div class="pc-value">{{ detailStock.trade_plan.risk_reward }} : 1</div>
              <div class="pc-sub">{{ detailStock.trade_plan.risk_reward >= 2 ? '✓ 优秀' : (detailStock.trade_plan.risk_reward >= 1.5 ? '可接受' : '一般') }}</div>
            </div>
          </div>
          <div v-if="detailStock.trade_plan.reasons?.length" class="plan-list">
            <div class="plan-list-title">💡 看好理由</div>
            <ul>
              <li v-for="(r, i) in detailStock.trade_plan.reasons" :key="'r'+i">{{ r }}</li>
            </ul>
          </div>
          <div v-if="detailStock.trade_plan.warnings?.length" class="plan-list warning">
            <div class="plan-list-title">⚠️ 风险提示</div>
            <ul>
              <li v-for="(w, i) in detailStock.trade_plan.warnings" :key="'w'+i">{{ w }}</li>
            </ul>
          </div>
        </div>

        <!-- 6 维度评分柱状图 -->
        <div class="drawer-section" v-if="detailStock.dim_scores">
          <div class="drawer-section-title">📊 6 维度评分</div>
          <v-chart
            class="dim-bar-chart"
            :option="getDimBarOption(detailStock)"
            autoresize
          />
        </div>

        <!-- 命中策略 -->
        <div class="drawer-section" v-if="detailStock.strategies?.length">
          <div class="drawer-section-title">
            🎯 命中策略（{{ detailStock.strategies.length }} 个）
          </div>
          <div class="strategy-detail-list">
            <div
              v-for="st in detailStock.strategies"
              :key="st.name"
              class="strategy-detail-item"
            >
              <div class="strategy-detail-name">
                <span class="check-icon">✓</span>{{ st.name }}
              </div>
              <div class="strategy-detail-desc">{{ st.desc }}</div>
            </div>
          </div>
        </div>

        <!-- 标签 -->
        <div class="drawer-section" v-if="detailStock.tags?.length">
          <div class="drawer-section-title">🏷️ 信号标签</div>
          <div class="tags-list">
            <el-tag
              v-for="tag in detailStock.tags"
              :key="tag"
              :type="tagType(tag)"
              effect="dark"
              size="default"
            >
              {{ tag }}
            </el-tag>
          </div>
        </div>

        <!-- 全部信号（按维度分组） -->
        <div class="drawer-section" v-if="detailStock.signals?.length">
          <div class="drawer-section-title">
            📡 触发信号（{{ detailStock.signals.length }} 个）
          </div>
          <div class="signals-grouped">
            <div
              v-for="grp in groupSignalsByDim(detailStock.signals)"
              :key="grp.dim"
              class="signal-group"
            >
              <div class="signal-group-title" :class="`dim-bg-${grp.dim}`">
                {{ dimLabel(grp.dim) }}
                <span class="signal-group-count">{{ grp.items.length }}</span>
              </div>
              <div class="signal-group-list">
                <div v-for="(sig, idx) in grp.items" :key="idx" class="signal-item">
                  <div class="signal-strength-icon" :class="`signal-${sig.strength}`">
                    {{ strengthIcon(sig.strength) }}
                  </div>
                  <div class="signal-content">
                    <div class="signal-text">{{ sig.desc }}</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 完整技术指标（按类别分组） -->
        <div class="drawer-section" v-if="detailStock.indicators">
          <div class="drawer-section-title">📐 技术指标</div>
          <div
            v-for="grp in indicatorGroups(detailStock.indicators)"
            :key="grp.title"
            class="indicator-group"
          >
            <div class="indicator-group-title">{{ grp.title }}</div>
            <div class="indicators-grid">
              <div v-for="cell in grp.cells" :key="cell.label" class="ind-cell">
                <div class="ind-label">{{ cell.label }}</div>
                <div class="ind-value" :class="cell.cls">{{ cell.value }}</div>
              </div>
            </div>
          </div>
        </div>

        <!-- 操作按钮 -->
        <div class="drawer-actions">
          <el-button type="primary" @click="goAnalyze(detailStock)">
            🤖 Agent 深度分析
          </el-button>
          <el-button type="success" @click="addWatchlist(detailStock)">
            + 加入自选股
          </el-button>
          <el-button @click="goKline(detailStock)">
            📉 查看K线
          </el-button>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
defineOptions({ name: 'Scanner' })
import { ref, reactive, computed, onMounted, onDeactivated, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Loading, ArrowRight, ArrowDown } from '@element-plus/icons-vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { RadarChart, BarChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  RadarComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { api } from '../api.js'

use([
  RadarChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  RadarComponent,
  CanvasRenderer,
])

const router = useRouter()

const scanning = ref(false)
const result = ref(null)
const drawerVisible = ref(false)
const detailStock = ref(null)
const paramsOpen = ref([])
const rejectedOpen = ref(false)

const strategies = ref([])
const selectedStrategies = ref([])

const elapsedSec = ref(0)
const estimateSec = ref(180)
const scanStage = ref('')
const scanStageDetail = ref('')
let _scanTimer = null
let _scanWs = null

const params = reactive({
  top_n: 20,
  min_score: 50,
  candidate_pool: 100,
  enable_fundamental: true,
  enable_llm: true,
  llm_top_n: 10,
})

// 维度满分配置
const DIM_MAX = {
  trend: 20,
  momentum: 15,
  volume: 20,
  pattern: 15,
  capital: 15,
  comprehensive: 15,
}
const DIM_NAMES = {
  trend: '趋势',
  momentum: '动量',
  volume: '量能',
  pattern: '形态',
  capital: '资金',
  comprehensive: '综合',
}
const DIM_COLORS = {
  trend: '#67c23a',
  momentum: '#e6a23c',
  volume: '#409eff',
  pattern: '#9b59b6',
  capital: '#f5b342',
  comprehensive: '#67c5d6',
}

const strategyGroups = computed(() => {
  const map = new Map()
  for (const s of strategies.value) {
    const cat = s.category || '其他'
    if (!map.has(cat)) map.set(cat, [])
    map.get(cat).push(s)
  }
  return Array.from(map.entries()).map(([category, items]) => ({ category, items }))
})

const STORAGE_KEY = 'scanner:last_result_v1'
const lastScanAt = ref(null)

function _loadCachedResult() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return
    const obj = JSON.parse(raw)
    if (obj?.result) {
      result.value = obj.result
      lastScanAt.value = obj.savedAt
      if (Array.isArray(obj.selected)) {
        selectedStrategies.value = obj.selected
      }
      if (obj.params && typeof obj.params === 'object') {
        Object.assign(params, obj.params)
      }
    }
  } catch (_) { /* ignore */ }
}

function _saveCachedResult() {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        result: result.value,
        savedAt: Date.now(),
        selected: selectedStrategies.value,
        params: { ...params },
      })
    )
    lastScanAt.value = Date.now()
  } catch (_) { /* ignore quota */ }
}

function clearSavedResult() {
  result.value = null
  lastScanAt.value = null
  localStorage.removeItem(STORAGE_KEY)
}

function fmtSavedAt(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

onMounted(async () => {
  // 先恢复上次扫描结果（即时显示，无需等接口）
  _loadCachedResult()
  try {
    const list = await api.scannerStrategies()
    strategies.value = Array.isArray(list) ? list : []
  } catch (e) {
    ElMessage.warning('策略列表加载失败：' + e.message)
  }
})

// keep-alive 时停掉计时器，避免离开页面后 setInterval 仍跑
onDeactivated(() => {
  if (_scanTimer) { clearInterval(_scanTimer); _scanTimer = null }
  if (_scanWs) { _scanWs.close(); _scanWs = null }
})
onUnmounted(() => {
  if (_scanTimer) { clearInterval(_scanTimer); _scanTimer = null }
  if (_scanWs) { _scanWs.close(); _scanWs = null }
})

async function runScan(forceRefresh = false) {
  scanning.value = true
  elapsedSec.value = 0
  scanStage.value = '准备扫描参数'
  scanStageDetail.value = ''
  // 三层漏斗预估：T1 (~candidate_pool*1.0s) + T2 (~30s 基本面) + T3 (~llm_top_n*15s LLM)
  const t1 = params.candidate_pool * 1.0
  const t2 = params.enable_fundamental ? 30 : 0
  const t3 = params.enable_llm ? params.llm_top_n * 15 : 0
  estimateSec.value = Math.max(60, Math.round(t1 + t2 + t3))
  if (_scanTimer) clearInterval(_scanTimer)
  _scanTimer = setInterval(() => { elapsedSec.value += 1 }, 1000)
  try {
    if (forceRefresh) {
      try { await api.scannerClearCache() } catch (_) {}
    }
    const payload = {
      ...params,
      use_cache: !forceRefresh,
    }
    if (selectedStrategies.value.length > 0) {
      payload.required_strategies = selectedStrategies.value
    }
    let data
    try {
      data = await scanWithWebSocket(payload)
    } catch (wsErr) {
      scanStage.value = '实时进度连接失败，已回退普通扫描'
      scanStageDetail.value = wsErr.message || ''
      data = await api.scannerScan(payload)
    }
    result.value = data
    _saveCachedResult()
    if (!data.results?.length) {
      ElMessage.warning('未找到符合条件的潜力股')
    } else {
      ElMessage.success(`扫描完成，找到 ${data.results.length} 只 AI 推荐潜力股`)
    }
  } catch (e) {
    ElMessage.error('扫描失败: ' + e.message)
  } finally {
    scanning.value = false
    scanStage.value = ''
    scanStageDetail.value = ''
    if (_scanTimer) { clearInterval(_scanTimer); _scanTimer = null }
    if (_scanWs) { _scanWs.close(); _scanWs = null }
  }
}

function scanWithWebSocket(payload) {
  return new Promise((resolve, reject) => {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/api/v1/scanner/ws/scan`)
    _scanWs = ws
    let settled = false
    const timeout = setTimeout(() => {
      if (settled) return
      settled = true
      try { ws.close() } catch (_) {}
      reject(new Error('扫描进度连接超时'))
    }, 15 * 60 * 1000)

    function finish(fn, value) {
      if (settled) return
      settled = true
      clearTimeout(timeout)
      fn(value)
    }

    ws.onopen = () => {
      scanStage.value = '连接实时扫描通道'
      ws.send(JSON.stringify(payload))
    }
    ws.onmessage = (e) => {
      let msg
      try { msg = JSON.parse(e.data) } catch (_) { return }
      const event = msg.event
      const data = msg.data || {}
      updateScanStage(event, data)
      if (event === 'done') {
        finish(resolve, data.result || {})
        try { ws.close() } catch (_) {}
      } else if (event === 'error') {
        finish(reject, new Error(data.message || '扫描失败'))
      }
    }
    ws.onerror = () => finish(reject, new Error('WebSocket 扫描连接失败'))
    ws.onclose = () => {
      if (!settled) finish(reject, new Error('WebSocket 扫描连接已断开'))
    }
  })
}

function updateScanStage(event, data) {
  if (event === 'tier1_start') {
    scanStage.value = 'Tier-1 技术海选中'
    scanStageDetail.value = `全市场 ${data.total || 0} 只股票，正在筛选候选池`
  } else if (event === 'tier1_done') {
    scanStage.value = 'Tier-1 技术海选完成'
    scanStageDetail.value = `通过技术评分 ${data.count || 0} 只`
  } else if (event === 'tier2_start') {
    scanStage.value = 'Tier-2 基本面与资金面过滤中'
    scanStageDetail.value = `正在评估 ${data.count || 0} 只股票`
  } else if (event === 'tier2_done') {
    scanStage.value = 'Tier-2 过滤完成'
    scanStageDetail.value = `剩余 ${data.count || 0} 只进入 AI 终审候选`
  } else if (event === 'tier3_start') {
    scanStage.value = 'Tier-3 AI 终审中'
    scanStageDetail.value = `正在让 AI 复核 ${data.count || 0} 只股票`
  } else if (event === 'tier3_progress') {
    scanStage.value = 'Tier-3 AI 终审中'
    scanStageDetail.value = `${data.completed || 0}/${data.total || 0} 已完成，当前 ${data.symbol || ''}`
  } else if (event === 'tier3_done') {
    scanStage.value = 'Tier-3 AI 终审完成'
    scanStageDetail.value = `AI 推荐 ${data.count || 0} 只，否决 ${data.rejected || 0} 只`
  } else if (event === 'done') {
    scanStage.value = '扫描完成'
    scanStageDetail.value = '正在渲染结果'
  }
}

function toggleStrategy(name) {
  const i = selectedStrategies.value.indexOf(name)
  if (i >= 0) selectedStrategies.value.splice(i, 1)
  else selectedStrategies.value.push(name)
}

function clearStrategies() {
  selectedStrategies.value = []
}

function selectAllStrategies() {
  selectedStrategies.value = strategies.value.map(s => s.name)
}

function openDetail(stock) {
  detailStock.value = stock
  drawerVisible.value = true
}

function goAnalyze(stock) {
  router.push({
    path: '/agent',
    query: { symbol: stock.symbol, name: stock.name, t: Date.now() },
  })
}

function goKline(stock) {
  router.push({ path: '/market', query: { symbol: stock.symbol, name: stock.name } })
}

function goTrade(stock) {
  const plan = stock.trade_plan || {}
  const evo = stock.evolution || {}
  const price = plan.entry_mid || plan.entry_low || stock.price || 0
  const reason = [
    `扫描推荐：${stock.name || stock.symbol}`,
    plan.rating ? `评级 ${plan.rating}` : '',
    evo.probability_pct ? `进化概率 ${evo.probability_pct}%/${evo.best_horizon_days}日` : '',
    plan.tomorrow_plan || '',
  ].filter(Boolean).join('；')
  router.push({
    path: '/trading',
    query: {
      symbol: stock.symbol,
      name: stock.name || '',
      side: 'BUY',
      price: price ? Number(price).toFixed(2) : '',
      reason,
      source: 'scanner',
    },
  })
}

async function addWatchlist(stock) {
  try {
    await api.watchlistAdd(stock.symbol, stock.name)
    ElMessage.success(`已添加 ${stock.name} 到自选股`)
  } catch (e) {
    ElMessage.error(e.message)
  }
}

// ===== ECharts 配置 =====
function getRadarOption(stock) {
  const ds = stock.dim_scores || {}
  return {
    radar: {
      indicator: [
        { name: '趋势', max: DIM_MAX.trend },
        { name: '动量', max: DIM_MAX.momentum },
        { name: '量能', max: DIM_MAX.volume },
        { name: '形态', max: DIM_MAX.pattern },
        { name: '资金', max: DIM_MAX.capital },
        { name: '综合', max: DIM_MAX.comprehensive },
      ],
      radius: 50,
      center: ['50%', '52%'],
      axisName: { color: '#909399', fontSize: 10 },
      splitLine: { lineStyle: { color: '#2a2a4a' } },
      splitArea: { show: false },
      axisLine: { lineStyle: { color: '#2a2a4a' } },
    },
    series: [
      {
        type: 'radar',
        data: [
          {
            value: [
              ds.trend || 0,
              ds.momentum || 0,
              ds.volume || 0,
              ds.pattern || 0,
              ds.capital || 0,
              ds.comprehensive || 0,
            ],
          },
        ],
        areaStyle: { color: 'rgba(64, 158, 255, 0.3)' },
        lineStyle: { color: '#409eff', width: 1.5 },
        symbol: 'none',
      },
    ],
  }
}

function getDimBarOption(stock) {
  const ds = stock.dim_scores || {}
  const order = ['trend', 'momentum', 'volume', 'pattern', 'capital', 'comprehensive']
  const data = order.map(k => ({
    value: ds[k] || 0,
    itemStyle: { color: DIM_COLORS[k], borderRadius: [0, 4, 4, 0] },
    max: DIM_MAX[k],
  }))
  return {
    grid: { left: 60, right: 50, top: 10, bottom: 24 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#16162a',
      borderColor: '#2a2a4a',
      textStyle: { color: '#c0c4cc' },
      formatter: (p) => {
        const it = p[0]
        const max = DIM_MAX[order[it.dataIndex]]
        return `${it.name}: <b>${it.value}</b> / ${max}`
      },
    },
    xAxis: {
      type: 'value',
      max: 20,
      axisLine: { lineStyle: { color: '#2a2a4a' } },
      axisLabel: { color: '#606266', fontSize: 10 },
      splitLine: { lineStyle: { color: '#2a2a4a' } },
    },
    yAxis: {
      type: 'category',
      data: order.map(k => DIM_NAMES[k]),
      axisLine: { lineStyle: { color: '#2a2a4a' } },
      axisLabel: { color: '#c0c4cc', fontSize: 12 },
    },
    series: [
      {
        type: 'bar',
        data,
        barWidth: 14,
        label: {
          show: true,
          position: 'right',
          formatter: (p) => `${p.value}/${DIM_MAX[order[p.dataIndex]]}`,
          color: '#c0c4cc',
          fontSize: 11,
        },
      },
    ],
  }
}

// ===== 工具函数 =====
function scoreLevel(score) {
  if (score >= 75) return 'high'
  if (score >= 60) return 'mid'
  return 'low'
}

function scoreColor(score) {
  if (score >= 75) return '#67c23a'
  if (score >= 60) return '#e6a23c'
  return '#909399'
}

function tagType(tag) {
  const positive = [
    '多头排列', 'MA5金叉', 'MA10金叉', 'MA20金叉', 'MACD金叉', 'MACD多头',
    '放量上涨', '突破高点', '突破平台', 'RSI反弹', '四线多头',
  ]
  const warning = ['超卖反弹', '超跌反弹', '高而窄旗形']
  const neutral = ['回踩MA20', '回踩年线', '停机坪']
  if (positive.includes(tag)) return 'success'
  if (warning.includes(tag)) return 'warning'
  if (neutral.includes(tag)) return 'info'
  return ''
}

function dimLabel(dim) {
  return DIM_NAMES[dim] || (dim || '其他')
}

function strengthIcon(s) {
  if (s === 'strong') return '🔥'
  if (s === 'good') return '✨'
  if (s === 'warn') return '⚠️'
  return '·'
}

function ratingClass(r) {
  if (r === '强烈推荐') return 'best'
  if (r === '推荐') return 'good'
  if (r === '观察') return 'watch'
  return 'skip'
}

function ratingTagType(r) {
  if (r === '强烈推荐') return 'danger'
  if (r === '推荐') return 'warning'
  if (r === '观察') return 'info'
  return ''
}

function aiActionLabel(a) {
  return { BUY: '建议买入', HOLD: '继续持有', WATCH: '观察', SELL: '建议卖出' }[a] || a
}

function aiActionTagType(a) {
  return { BUY: 'danger', HOLD: 'warning', WATCH: 'info', SELL: 'success' }[a] || 'info'
}

function confColor(v) {
  if (v == null) return '#909399'
  if (v >= 80) return '#f56c6c'
  if (v >= 65) return '#e6a23c'
  if (v >= 50) return '#67c23a'
  return '#909399'
}

function dimColor(value, max) {
  if (value == null) return '#606266'
  const pct = (value / max) * 100
  if (pct >= 80) return '#f56c6c'
  if (pct >= 60) return '#e6a23c'
  if (pct >= 40) return '#67c23a'
  return '#909399'
}

function riskColor(value, max) {
  if (value == null) return '#606266'
  const pct = (value / max) * 100
  if (pct >= 65) return '#67c23a'
  if (pct >= 35) return '#e6a23c'
  return '#f56c6c'
}

function peClass(pe) {
  if (pe == null) return ''
  if (pe < 0) return 'down'
  if (pe > 100) return 'down'
  if (pe <= 30) return 'up'
  return ''
}

function industryScoreClass(v) {
  if (v == null) return ''
  if (v >= 10) return 'up'
  if (v <= 4) return 'down'
  return ''
}

function sentimentTagType(s) {
  const map = {
    强势: 'danger',
    偏强: 'warning',
    中性: 'info',
    偏弱: 'success',
    弱势: 'success',
  }
  return map[s] || 'info'
}

function rsiClass(v) {
  if (v == null) return ''
  if (v > 70) return 'down'
  if (v < 30) return 'up'
  return ''
}

function signClass(v) {
  if (v == null) return ''
  if (v > 0) return 'up'
  if (v < 0) return 'down'
  return ''
}

function numFmt(v, digits = 2) {
  if (v == null || Number.isNaN(v)) return '—'
  return typeof v === 'number' ? v.toFixed(digits) : String(v)
}

function fmtAmt(v) {
  if (!v) return '—'
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (v >= 1e4) return (v / 1e4).toFixed(0) + '万'
  return v.toFixed(0)
}

function fmtShares(v) {
  if (!v) return '—'
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿股'
  if (v >= 1e4) return (v / 1e4).toFixed(0) + '万股'
  return Number(v).toFixed(0) + '股'
}

function fmtSignedAmt(v) {
  if (v == null || Number.isNaN(v)) return '—'
  const sign = v >= 0 ? '+' : '-'
  return sign + fmtAmt(Math.abs(v))
}

function fmtSignedPct(v) {
  if (v == null || Number.isNaN(v)) return '—'
  return `${v >= 0 ? '+' : ''}${Number(v).toFixed(2)}%`
}

function groupSignalsByDim(signals) {
  const order = ['trend', 'momentum', 'volume', 'pattern', 'capital', 'comprehensive', 'other']
  const map = new Map()
  for (const sig of signals) {
    const key = sig.dim || 'other'
    if (!map.has(key)) map.set(key, [])
    map.get(key).push(sig)
  }
  const out = []
  for (const k of order) {
    if (map.has(k)) out.push({ dim: k, items: map.get(k) })
  }
  // 添加任何不在 order 中的（容错）
  for (const [k, items] of map) {
    if (!order.includes(k)) out.push({ dim: k, items })
  }
  return out
}

function indicatorGroups(ind) {
  const groups = [
    {
      title: '均线',
      cells: [
        { label: 'MA5', value: numFmt(ind.ma5) },
        { label: 'MA10', value: numFmt(ind.ma10) },
        { label: 'MA20', value: numFmt(ind.ma20) },
        { label: 'MA60', value: numFmt(ind.ma60) },
      ],
    },
    {
      title: 'RSI / KDJ',
      cells: [
        { label: 'RSI14', value: numFmt(ind.rsi14), cls: rsiClass(ind.rsi14) },
        { label: 'KDJ-K', value: numFmt(ind.kdj_k) },
        { label: 'KDJ-D', value: numFmt(ind.kdj_d) },
        { label: 'KDJ-J', value: numFmt(ind.kdj_j) },
      ],
    },
    {
      title: 'MACD',
      cells: [
        { label: 'DIF', value: numFmt(ind.macd_dif, 3), cls: signClass(ind.macd_dif) },
        { label: 'DEA', value: numFmt(ind.macd_dea, 3), cls: signClass(ind.macd_dea) },
        { label: 'HIST', value: numFmt(ind.macd_hist, 3), cls: signClass(ind.macd_hist) },
      ],
    },
    {
      title: '量能',
      cells: [
        {
          label: '量比',
          value: ind.vol_ratio != null ? numFmt(ind.vol_ratio) + '×' : '—',
        },
        {
          label: '20日量比',
          value: ind.vol_ratio_20d != null ? numFmt(ind.vol_ratio_20d) + '×' : '—',
        },
        {
          label: '20日量增',
          value: ind.vol_20d_pct != null ? numFmt(ind.vol_20d_pct) + '%' : '—',
        },
        {
          label: 'ATR14',
          value: numFmt(ind.atr14),
        },
      ],
    },
    {
      title: '位置',
      cells: [
        {
          label: '20日位置',
          value: ind.pos_in_20d != null ? numFmt(ind.pos_in_20d) + '%' : '—',
        },
        { label: '20日高', value: numFmt(ind.high_20) },
        { label: '20日低', value: numFmt(ind.low_20) },
        { label: '60日高', value: numFmt(ind.high_60) },
        { label: '60日低', value: numFmt(ind.low_60) },
      ],
    },
    {
      title: '涨幅',
      cells: [
        {
          label: '今日',
          value:
            ind.today_pct != null
              ? (ind.today_pct >= 0 ? '+' : '') + numFmt(ind.today_pct) + '%'
              : '—',
          cls: signClass(ind.today_pct),
        },
        {
          label: '5日',
          value:
            ind.ret_5d != null
              ? (ind.ret_5d >= 0 ? '+' : '') + numFmt(ind.ret_5d) + '%'
              : '—',
          cls: signClass(ind.ret_5d),
        },
        {
          label: '20日',
          value:
            ind.ret_20d != null
              ? (ind.ret_20d >= 0 ? '+' : '') + numFmt(ind.ret_20d) + '%'
              : '—',
          cls: signClass(ind.ret_20d),
        },
      ],
    },
  ]
  return groups
}
</script>

<style scoped>
.scanner-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding-bottom: 40px;
}

/* 顶部标题 */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 12px;
  padding: 16px 20px;
  background: linear-gradient(135deg, #1a1a2e 0%, #1d1d36 100%);
  border: 1px solid #2a2a4a;
  border-radius: 10px;
}
.header-left { display: flex; flex-direction: column; gap: 4px; }
.page-title {
  font-size: 22px;
  font-weight: 700;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  color: #e0e0e0;
}
.title-icon { font-size: 26px; }
.page-subtitle { font-size: 12px; color: #909399; }
.header-actions { display: flex; gap: 8px; flex-wrap: wrap; }

/* 策略选择器 */
.strategy-card {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 10px;
  padding: 16px 18px;
}
.strategy-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
  flex-wrap: wrap;
  gap: 10px;
}
.strategy-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  font-weight: 600;
  color: #c0c4cc;
}
.strategy-count {
  font-size: 12px;
  color: #909399;
  font-weight: 400;
  background: #16162a;
  padding: 2px 10px;
  border-radius: 10px;
}
.strategy-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }

.strategy-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #909399;
  font-size: 13px;
  padding: 10px 0;
}

.strategy-groups {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.strategy-group {}
.group-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 600;
  color: #909399;
  margin-bottom: 8px;
  letter-spacing: 0.5px;
}
.group-dot {
  width: 4px;
  height: 14px;
  background: linear-gradient(180deg, #409eff, #67c23a);
  border-radius: 2px;
}
.group-count {
  font-size: 11px;
  color: #606266;
  font-weight: 400;
}

.strategy-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px;
}

.strategy-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  background: #16162a;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
  position: relative;
}
.strategy-item:hover {
  border-color: #409eff;
  background: #1c1c34;
}
.strategy-item.active {
  border-color: #67c23a;
  background: rgba(103, 194, 58, 0.08);
  box-shadow: 0 0 0 1px rgba(103, 194, 58, 0.4) inset;
}
.strategy-check {
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: 1.5px solid #2a2a4a;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  color: #fff;
  margin-top: 1px;
  background: #1a1a2e;
}
.strategy-item.active .strategy-check {
  background: #67c23a;
  border-color: #67c23a;
}
.strategy-info { flex: 1; min-width: 0; }
.strategy-name {
  font-size: 13px;
  font-weight: 600;
  color: #e0e0e0;
  margin-bottom: 3px;
}
.strategy-item.active .strategy-name { color: #67c23a; }
.strategy-desc {
  font-size: 11px;
  color: #909399;
  line-height: 1.5;
}

/* 参数折叠 */
.params-collapse {
  background: #1a1a2e !important;
  border: 1px solid #2a2a4a !important;
  border-radius: 8px;
  overflow: hidden;
}
.params-collapse :deep(.el-collapse-item__header) {
  background: #1a1a2e;
  border-bottom: 1px solid #2a2a4a;
  color: #c0c4cc;
  padding: 0 18px;
  font-size: 13px;
}
.params-collapse :deep(.el-collapse-item__wrap) {
  background: #1a1a2e;
  border-bottom: none;
}
.params-collapse :deep(.el-collapse-item__content) {
  padding: 14px 18px;
}
.collapse-title { font-weight: 600; }
.collapse-summary {
  font-size: 11px;
  color: #606266;
  margin-left: 12px;
  font-family: monospace;
}

.params-row {
  display: flex;
  gap: 24px;
  align-items: center;
  flex-wrap: wrap;
}
.param-item { display: flex; align-items: center; gap: 8px; }
.param-label { font-size: 13px; color: #909399; white-space: nowrap; }
.param-hint {
  font-size: 11px;
  color: #606266;
  margin-left: auto;
}

/* 进度提示 */
.scanning-tip {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  background: rgba(64, 158, 255, 0.08);
  border: 1px solid rgba(64, 158, 255, 0.3);
  border-radius: 8px;
  color: #409eff;
  font-size: 13px;
}
.scanning-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.scanning-title { color: #409eff; font-weight: 500; }
.scanning-stage-detail {
  color: #a7b7cc;
  font-size: 12px;
}
.scanning-progress {
  display: flex;
  align-items: center;
  gap: 12px;
}
.scanning-progress :deep(.el-progress) { flex: 1; }
.scanning-elapsed {
  color: #c0c4cc;
  font-size: 12px;
  font-family: monospace;
  white-space: nowrap;
  min-width: 180px;
  text-align: right;
}

/* 大盘状态 */
.market-card {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 10px;
  padding: 16px 20px;
}
.market-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}
.market-title { font-size: 14px; font-weight: 600; color: #c0c4cc; }
.indices-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr) 2fr;
  gap: 12px;
}
@media (max-width: 900px) {
  .indices-row { grid-template-columns: 1fr 1fr; }
}
.index-card {
  background: #16162a;
  border: 1px solid #2a2a4a;
  border-radius: 6px;
  padding: 10px 14px;
}
.idx-name { font-size: 11px; color: #909399; margin-bottom: 4px; }
.idx-price { font-size: 18px; font-weight: 600; }
.idx-pct { font-size: 12px; margin-top: 2px; }
.market-stats {
  background: #16162a;
  border: 1px solid #2a2a4a;
  border-radius: 6px;
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  justify-content: center;
}
.stat-row { display: flex; gap: 12px; align-items: center; font-size: 12px; }
.stat-label { color: #909399; }
.stat-val { font-weight: 600; font-family: monospace; }
.up-ratio {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
}
.ratio-val { color: #c0c4cc; font-family: monospace; min-width: 40px; text-align: right; }

/* 热门行业 */
.hot-industries {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 10px 16px;
  background: linear-gradient(135deg, rgba(245, 108, 108, 0.06), rgba(245, 179, 66, 0.04));
  border: 1px solid rgba(245, 108, 108, 0.15);
  border-radius: 8px;
}
.hot-icon { font-size: 16px; }
.hot-label { font-size: 13px; color: #c0c4cc; font-weight: 600; }
.hot-tag { font-family: monospace; }

.llm-status-alert {
  margin: 0;
}

/* AI 否决 */
.rejected-section {
  background: #1a1a2e;
  border: 1px dashed #2a2a4a;
  border-radius: 8px;
  overflow: hidden;
}
.rejected-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  cursor: pointer;
  flex-wrap: wrap;
}
.rejected-header:hover { background: #1c1c34; }
.rejected-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #909399;
  font-weight: 600;
}
.rejected-hint {
  font-size: 11px;
  color: #606266;
  margin-left: auto;
}
.rejected-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 4px 16px 12px;
}
.rejected-item {
  display: grid;
  grid-template-columns: 200px 110px 1fr;
  gap: 10px;
  align-items: center;
  padding: 8px 12px;
  background: #16162a;
  border-radius: 6px;
  cursor: pointer;
  transition: border-color 0.15s;
  border: 1px solid transparent;
  font-size: 12px;
}
.rejected-item:hover { border-color: #2a2a4a; }
.rj-id { display: flex; align-items: center; gap: 8px; min-width: 0; }
.rj-name { color: #c0c4cc; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rj-symbol { color: #606266; font-family: monospace; }
.rj-reason { color: #909399; line-height: 1.5; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
@media (max-width: 768px) {
  .rejected-item { grid-template-columns: 1fr; }
}

/* 扫描汇总 */
.scan-summary {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 14px 20px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  flex-wrap: wrap;
}
.summary-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 70px;
}
.summary-label { font-size: 11px; color: #606266; }
.summary-value { font-size: 18px; font-weight: 700; color: #c0c4cc; }
.summary-item.highlight .summary-value { color: #67c23a; font-size: 22px; }
.arrow { color: #606266; font-size: 16px; }
.summary-time { margin-left: auto; }

/* 股票卡片网格 */
.stocks-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 14px;
}
.stock-card {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 10px;
  padding: 14px 16px;
  cursor: pointer;
  position: relative;
  transition: transform 0.15s, border-color 0.15s, box-shadow 0.15s;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.stock-card:hover {
  transform: translateY(-2px);
  border-color: #409eff;
  box-shadow: 0 4px 16px rgba(64, 158, 255, 0.15);
}
.stock-card.score-high { border-left: 3px solid #67c23a; }
.stock-card.score-mid  { border-left: 3px solid #e6a23c; }
.stock-card.score-low  { border-left: 3px solid #909399; }

.rank-badge {
  position: absolute;
  top: 12px;
  right: 12px;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: #2a2a4a;
  color: #909399;
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1;
}
.rank-badge.rank-top {
  background: linear-gradient(135deg, #f5b342, #ff7e7e);
  color: #fff;
  box-shadow: 0 2px 8px rgba(245, 179, 66, 0.4);
}

.stock-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}
.stock-id { min-width: 0; flex: 1; }
.stock-name {
  font-size: 16px;
  font-weight: 700;
  color: #e0e0e0;
  margin-bottom: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.stock-symbol { font-size: 11px; color: #606266; font-family: monospace; }

.stock-score {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-right: 32px;
}
.score-value { font-size: 28px; font-weight: 800; line-height: 1; }
.stock-card.score-high .score-value { color: #67c23a; }
.stock-card.score-mid  .score-value { color: #e6a23c; }
.stock-card.score-low  .score-value { color: #909399; }
.score-label { font-size: 10px; color: #606266; }

/* 卡片头部右侧 AI 评级 */
.stock-action {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  margin-right: 32px;
}
.action-conf {
  font-size: 11px;
  color: #909399;
  font-family: monospace;
}

/* 4 维独立评分行 */
.dim-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  padding: 8px 12px;
  background: #16162a;
  border-radius: 6px;
}
@media (max-width: 480px) {
  .dim-row { grid-template-columns: repeat(2, 1fr); }
}
.dim-cell {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.dim-cell-label {
  font-size: 10px;
  color: #909399;
  font-weight: 600;
}
.dim-cell-bar {
  height: 4px;
  background: #1a1a2e;
  border-radius: 2px;
  overflow: hidden;
}
.dim-cell-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s;
}
.dim-cell-value {
  font-size: 11px;
  color: #c0c4cc;
  font-family: monospace;
}

.stock-price-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 8px 12px;
  background: #16162a;
  border-radius: 6px;
}
.stock-price { font-size: 17px; font-weight: 600; color: #e0e0e0; }
.stock-pct { font-size: 14px; font-weight: 600; }

.evo-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
}
.evo-pill {
  background: #141c32;
  border: 1px solid #2a3a64;
  border-radius: 8px;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.evo-pill.primary { border-color: #409eff; background: #10233d; }
.evo-pill span { color: #909399; font-size: 10px; }
.evo-pill b { color: #e0e0e0; font-size: 16px; font-family: monospace; }

/* 卡片中部：雷达 + 标签 */
.card-mid {
  display: grid;
  grid-template-columns: 160px 1fr;
  gap: 8px;
  align-items: stretch;
}
.radar-wrap {
  background: #16162a;
  border-radius: 8px;
  padding: 4px;
}
.radar-chart {
  width: 160px;
  height: 140px;
}
.card-side {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
  justify-content: center;
}
.card-strategies {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.strategy-tag { font-size: 11px !important; cursor: help; }
.card-tags {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.stock-tag { font-size: 11px !important; }

/* 信号区 */
.stock-signals {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 10px;
  background: #16162a;
  border-radius: 6px;
}
.signal-line {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #c0c4cc;
  line-height: 1.4;
}
.signal-dim-tag {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 3px;
  flex-shrink: 0;
  min-width: 32px;
  text-align: center;
}
.signal-dim-tag.dim-trend         { background: rgba(103, 194, 58, 0.18); color: #67c23a; }
.signal-dim-tag.dim-momentum      { background: rgba(230, 162, 60, 0.18); color: #e6a23c; }
.signal-dim-tag.dim-volume        { background: rgba(64, 158, 255, 0.18); color: #409eff; }
.signal-dim-tag.dim-pattern       { background: rgba(155, 89, 182, 0.20); color: #b97cd6; }
.signal-dim-tag.dim-capital       { background: rgba(245, 179, 66, 0.18); color: #f5b342; }
.signal-dim-tag.dim-comprehensive { background: rgba(103, 197, 214, 0.18); color: #67c5d6; }
.signal-dim-tag.dim-other         { background: rgba(144, 147, 153, 0.18); color: #909399; }

.signal-dot { font-size: 8px; line-height: 1.5; flex-shrink: 0; }
.signal-strong { color: #67c23a; }
.signal-good   { color: #409eff; }
.signal-ok     { color: #909399; }
.signal-warn   { color: #e6a23c; }

.signal-desc {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.signal-more {
  font-size: 11px;
  color: #606266;
  text-align: center;
  margin-top: 2px;
}

.stock-actions { display: flex; gap: 6px; flex-wrap: wrap; }

/* AI 终审块 */
.ai-verdict {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  border-radius: 8px;
  background: linear-gradient(135deg, rgba(64, 158, 255, 0.10), rgba(103, 197, 214, 0.04));
  border: 1px solid rgba(64, 158, 255, 0.30);
}
.ai-verdict.ai-buy  { border-color: rgba(245, 108, 108, 0.45); background: linear-gradient(135deg, rgba(245, 108, 108, 0.12), rgba(245, 179, 66, 0.06)); }
.ai-verdict.ai-hold { border-color: rgba(230, 162, 60, 0.40); background: linear-gradient(135deg, rgba(230, 162, 60, 0.10), rgba(230, 162, 60, 0.04)); }
.ai-verdict.ai-sell { border-color: rgba(103, 194, 58, 0.40); background: linear-gradient(135deg, rgba(103, 194, 58, 0.10), rgba(103, 194, 58, 0.04)); }
.ai-header {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.ai-icon { font-size: 14px; }
.ai-title { font-size: 12px; color: #c0c4cc; font-weight: 600; }
.ai-conf { font-size: 12px; font-weight: 700; margin-left: auto; font-family: monospace; }
.ai-quote {
  font-size: 12px;
  color: #c0c4cc;
  line-height: 1.5;
  font-style: italic;
}

/* 基本面 + 资金面一行 */
.fund-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding: 6px 10px;
  background: #16162a;
  border-radius: 6px;
  font-size: 11px;
  color: #909399;
}
.fund-cell { white-space: nowrap; }
.fund-cell b {
  font-family: monospace;
  font-size: 12px;
  color: #c0c4cc;
  margin-left: 3px;
}
.fund-cell b.up { color: #f56c6c; }
.fund-cell b.down { color: #67c23a; }
.industry-cell em {
  color: #f5b342;
  font-style: normal;
  font-family: monospace;
  margin-left: 4px;
}

/* 明日交易计划（卡片紧凑版） */
.trade-plan {
  background: linear-gradient(135deg, rgba(245, 108, 108, 0.06), rgba(245, 179, 66, 0.04));
  border: 1px solid rgba(245, 108, 108, 0.25);
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.trade-plan.plan-best  { border-color: rgba(245, 108, 108, 0.55); background: linear-gradient(135deg, rgba(245, 108, 108, 0.12), rgba(245, 179, 66, 0.08)); }
.trade-plan.plan-good  { border-color: rgba(245, 179, 66, 0.40); }
.trade-plan.plan-watch { border-color: rgba(64, 158, 255, 0.30); background: linear-gradient(135deg, rgba(64, 158, 255, 0.06), rgba(64, 158, 255, 0.02)); }
.trade-plan.plan-skip  { border-color: rgba(144, 147, 153, 0.30); background: rgba(22, 22, 42, 0.8); }
.plan-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: #909399;
}
.plan-horizon, .plan-pos { font-size: 11px; }
.plan-pos { margin-left: auto; color: #c0c4cc; }
.plan-prices {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 6px;
}
.pp-cell {
  background: #16162a;
  border-radius: 6px;
  padding: 6px 8px;
  text-align: center;
}
.pp-label { font-size: 10px; color: #606266; margin-bottom: 2px; }
.pp-val { font-size: 13px; font-weight: 700; font-family: monospace; }
.pp-val.buy  { color: #f56c6c; }
.pp-val.stop { color: #67c23a; }
.pp-val.tgt  { color: #e6a23c; }
.plan-rr {
  display: flex;
  gap: 12px;
  font-size: 11px;
  color: #909399;
  flex-wrap: wrap;
}
.plan-rr b { font-family: monospace; font-size: 12px; }
.plan-tomorrow {
  font-size: 12px;
  color: #c0c4cc;
  background: #16162a;
  padding: 6px 10px;
  border-radius: 6px;
  border-left: 3px solid #f5b342;
  line-height: 1.5;
}

/* 明日交易计划（抽屉详细版） */
.drawer-plan.plan-best  { border-left: 4px solid #f56c6c; }
.drawer-plan.plan-good  { border-left: 4px solid #e6a23c; }
.drawer-plan.plan-watch { border-left: 4px solid #409eff; }
.drawer-plan.plan-skip  { border-left: 4px solid #909399; }
.plan-tomorrow-big {
  font-size: 14px;
  color: #c0c4cc;
  background: #1a1a2e;
  padding: 10px 14px;
  border-radius: 6px;
  border-left: 3px solid #f5b342;
  line-height: 1.6;
  margin-bottom: 12px;
}
.plan-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-bottom: 12px;
}
.plan-cell {
  background: #1a1a2e;
  border-radius: 6px;
  padding: 10px 12px;
}
.pc-label { font-size: 11px; color: #909399; margin-bottom: 4px; }
.pc-value {
  font-size: 16px;
  font-weight: 700;
  font-family: monospace;
  color: #e0e0e0;
}
.pc-value.buy  { color: #f56c6c; }
.pc-value.stop { color: #67c23a; }
.pc-value.tgt  { color: #e6a23c; }
.pc-sub { font-size: 11px; color: #606266; margin-top: 2px; font-family: monospace; }
.pc-sub.up   { color: #f56c6c; }
.pc-sub.down { color: #67c23a; }

.plan-list {
  background: #1a1a2e;
  border-radius: 6px;
  padding: 10px 14px;
  margin-top: 8px;
}
.plan-list.warning { border-left: 3px solid #e6a23c; }
.plan-list-title {
  font-size: 12px;
  color: #c0c4cc;
  font-weight: 600;
  margin-bottom: 6px;
}
.plan-list ul { padding-left: 20px; }
.plan-list li {
  font-size: 12px;
  color: #909399;
  line-height: 1.7;
  margin-bottom: 2px;
}

/* 颜色（A 股习惯） */
.up   { color: #f56c6c; }
.down { color: #67c23a; }

/* 空状态 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  padding: 50px 20px;
  background: #1a1a2e;
  border: 1px dashed #2a2a4a;
  border-radius: 10px;
}
.empty-icon { font-size: 48px; opacity: 0.6; }
.empty-text { font-size: 14px; color: #909399; }

.scan-explain {
  max-width: 720px;
  font-size: 13px;
  color: #c0c4cc;
  line-height: 1.8;
  background: #16162a;
  padding: 16px 20px;
  border-radius: 8px;
  margin-top: 8px;
}
.dim-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
  gap: 8px;
  margin-top: 8px;
}
.dim-card {
  background: #1a1a2e;
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.dim-icon { font-size: 14px; }
.dim-max { color: #606266; margin-left: auto; font-family: monospace; }
.tag-cloud { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }

/* 抽屉 */
.drawer-content {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 4px 0;
}

/* AI 终审主卡 */
.drawer-ai-card {
  background: linear-gradient(135deg, rgba(64, 158, 255, 0.10), rgba(103, 197, 214, 0.04));
  border: 1px solid rgba(64, 158, 255, 0.30);
  border-radius: 10px;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.drawer-ai-card.ai-buy  { border-color: rgba(245, 108, 108, 0.55); background: linear-gradient(135deg, rgba(245, 108, 108, 0.14), rgba(245, 179, 66, 0.06)); }
.drawer-ai-card.ai-hold { border-color: rgba(230, 162, 60, 0.45); background: linear-gradient(135deg, rgba(230, 162, 60, 0.12), rgba(230, 162, 60, 0.04)); }
.drawer-ai-card.ai-sell { border-color: rgba(103, 194, 58, 0.45); background: linear-gradient(135deg, rgba(103, 194, 58, 0.12), rgba(103, 194, 58, 0.04)); }
.dac-header {
  display: flex;
  align-items: center;
  gap: 10px;
}
.dac-conf {
  font-size: 13px;
  color: #c0c4cc;
  font-weight: 700;
  font-family: monospace;
  margin-left: auto;
}
.dac-quote {
  font-size: 14px;
  color: #c0c4cc;
  line-height: 1.6;
  font-style: italic;
}
.dac-advice {
  display: flex;
  flex-direction: column;
  gap: 6px;
  background: rgba(22, 22, 42, 0.5);
  border-radius: 6px;
  padding: 8px 12px;
}
.advice-line {
  font-size: 12px;
  color: #c0c4cc;
  line-height: 1.5;
}
.advice-label {
  color: #909399;
  font-weight: 600;
  margin-right: 6px;
}

/* 4 维评分卡 */
.drawer-multi-score {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(92px, 1fr));
  gap: 8px;
}
.dms-cell {
  background: #16162a;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  padding: 12px 10px;
  text-align: center;
}
.dms-label { font-size: 11px; color: #909399; margin-bottom: 4px; }
.dms-value { font-size: 28px; font-weight: 800; line-height: 1; font-family: monospace; }
.dms-max { font-size: 11px; color: #606266; margin-top: 2px; font-family: monospace; }

.evolution-detail {
  border-color: rgba(64, 158, 255, 0.35) !important;
  background: linear-gradient(135deg, rgba(64, 158, 255, 0.10), rgba(26, 26, 46, 0.65));
}
.evo-big-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}
.evo-big-cell {
  background: #16162a;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  padding: 10px;
}
.evo-big-label { color: #909399; font-size: 11px; margin-bottom: 6px; }
.evo-big-value { color: #fff; font-size: 20px; font-weight: 800; font-family: monospace; }
.evo-horizons {
  margin-top: 10px;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 6px;
}
.evo-horizon {
  display: flex;
  justify-content: space-between;
  background: #111827;
  border-radius: 6px;
  padding: 7px 9px;
  color: #909399;
  font-size: 12px;
}
.evo-horizon b { color: #7db7ff; font-family: monospace; }

.drawer-meta {
  display: flex;
  gap: 14px;
  background: #1a1a2e;
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 13px;
  color: #c0c4cc;
}
.drawer-meta .up { color: #f56c6c; }
.drawer-meta .down { color: #67c23a; }

.industry-detail {
  border: 1px solid rgba(245, 179, 66, 0.22);
  background: linear-gradient(135deg, rgba(245, 179, 66, 0.08), rgba(22, 22, 42, 0.88));
}
.northbound-detail {
  border: 1px solid rgba(64, 158, 255, 0.22);
  background: linear-gradient(135deg, rgba(64, 158, 255, 0.08), rgba(22, 22, 42, 0.88));
}
.research-detail {
  border: 1px solid rgba(103, 194, 58, 0.22);
  background: linear-gradient(135deg, rgba(103, 194, 58, 0.08), rgba(22, 22, 42, 0.88));
}
.reduction-detail {
  border: 1px solid rgba(245, 108, 108, 0.26);
  background: linear-gradient(135deg, rgba(245, 108, 108, 0.09), rgba(22, 22, 42, 0.88));
}
.industry-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(116px, 1fr));
  gap: 8px;
}
.industry-cell-big {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  padding: 10px 12px;
}
.industry-cell-big span {
  display: block;
  color: #909399;
  font-size: 11px;
  margin-bottom: 4px;
}
.industry-cell-big b {
  color: #e0e0e0;
  font-size: 15px;
  font-family: monospace;
}
.industry-cell-big b.up { color: #f56c6c; }
.industry-cell-big b.down { color: #67c23a; }
.industry-items { margin-top: 10px; }
.research-list {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.research-item {
  display: grid;
  grid-template-columns: 78px 58px 1fr 76px;
  gap: 8px;
  align-items: center;
  padding: 7px 9px;
  background: #1a1a2e;
  border-radius: 6px;
  color: #909399;
  font-size: 12px;
}
.research-date,
.research-rating,
.research-org {
  font-family: monospace;
  white-space: nowrap;
}
.research-rating { color: #f5b342; }
.research-org.down { color: #67c23a; }
.research-title {
  color: #c0c4cc;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
@media (max-width: 640px) {
  .research-item { grid-template-columns: 1fr; }
}
.reduction-item {
  grid-template-columns: 78px 72px 1fr 86px;
}

/* 基本面/资金面 items */
.fund-items {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.fund-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px;
  border-radius: 6px;
  background: #1a1a2e;
  font-size: 12px;
}
.fund-item.fi-good    { border-left: 3px solid #67c23a; }
.fund-item.fi-neutral { border-left: 3px solid #909399; }
.fund-item.fi-warn    { border-left: 3px solid #e6a23c; }
.fund-item.fi-bad     { border-left: 3px solid #f56c6c; }
.fi-score {
  font-family: monospace;
  font-weight: 700;
  font-size: 13px;
  color: #c0c4cc;
  min-width: 32px;
}
.fi-desc {
  flex: 1;
  color: #909399;
  line-height: 1.5;
}

.ai-points {
  padding-left: 18px;
  margin: 0;
}
.ai-points li {
  font-size: 12px;
  color: #c0c4cc;
  line-height: 1.7;
  margin-bottom: 2px;
}
.ap-sub-title {
  font-size: 11px;
  color: #909399;
  font-weight: 600;
  margin-bottom: 4px;
}
.ap-sub-title.up { color: #67c23a; }
.ap-sub-title.down { color: #e6a23c; }

.score-card {
  background: #16162a;
  border: 1px solid #2a2a4a;
  border-radius: 10px;
  padding: 18px;
  text-align: center;
}
.score-card.score-high { border-color: #67c23a; }
.score-card.score-mid  { border-color: #e6a23c; }
.score-card.score-low  { border-color: #909399; }
.sc-score-label { font-size: 12px; color: #909399; margin-bottom: 4px; }
.sc-score-value { font-size: 48px; font-weight: 800; line-height: 1; margin-bottom: 8px; }
.score-card.score-high .sc-score-value { color: #67c23a; }
.score-card.score-mid  .sc-score-value { color: #e6a23c; }
.score-card.score-low  .sc-score-value { color: #909399; }
.sc-score-bar { margin: 12px 0; }
.sc-meta {
  display: flex;
  gap: 16px;
  justify-content: center;
  font-size: 13px;
  color: #c0c4cc;
}

.drawer-section {
  background: #16162a;
  border-radius: 8px;
  padding: 14px 16px;
}
.drawer-section-title {
  font-size: 13px;
  font-weight: 600;
  color: #c0c4cc;
  margin-bottom: 10px;
}

.dim-bar-chart {
  width: 100%;
  height: 220px;
}

/* 命中策略列表 */
.strategy-detail-list { display: flex; flex-direction: column; gap: 8px; }
.strategy-detail-item {
  background: rgba(103, 194, 58, 0.08);
  border: 1px solid rgba(103, 194, 58, 0.3);
  border-radius: 6px;
  padding: 8px 12px;
}
.strategy-detail-name {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #67c23a;
}
.check-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #67c23a;
  color: #fff;
  font-size: 10px;
  font-weight: 700;
}
.strategy-detail-desc {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
  line-height: 1.5;
}

.tags-list { display: flex; gap: 6px; flex-wrap: wrap; }

/* 信号分组 */
.signals-grouped { display: flex; flex-direction: column; gap: 12px; }
.signal-group {}
.signal-group-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  margin-bottom: 6px;
}
.signal-group-title.dim-bg-trend         { background: rgba(103, 194, 58, 0.18); color: #67c23a; }
.signal-group-title.dim-bg-momentum      { background: rgba(230, 162, 60, 0.18); color: #e6a23c; }
.signal-group-title.dim-bg-volume        { background: rgba(64, 158, 255, 0.18); color: #409eff; }
.signal-group-title.dim-bg-pattern       { background: rgba(155, 89, 182, 0.20); color: #b97cd6; }
.signal-group-title.dim-bg-capital       { background: rgba(245, 179, 66, 0.18); color: #f5b342; }
.signal-group-title.dim-bg-comprehensive { background: rgba(103, 197, 214, 0.18); color: #67c5d6; }
.signal-group-title.dim-bg-other         { background: rgba(144, 147, 153, 0.18); color: #909399; }
.signal-group-count {
  font-size: 10px;
  font-weight: 400;
  opacity: 0.7;
}
.signal-group-list { display: flex; flex-direction: column; gap: 6px; padding-left: 4px; }
.signal-item { display: flex; gap: 10px; align-items: flex-start; }
.signal-strength-icon { font-size: 14px; flex-shrink: 0; line-height: 1.4; }
.signal-content { flex: 1; }
.signal-text { font-size: 13px; color: #c0c4cc; line-height: 1.5; }

/* 指标分组 */
.indicator-group { margin-bottom: 12px; }
.indicator-group:last-child { margin-bottom: 0; }
.indicator-group-title {
  font-size: 11px;
  color: #909399;
  margin-bottom: 6px;
  font-weight: 600;
  letter-spacing: 0.5px;
}
.indicators-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(78px, 1fr));
  gap: 6px;
}
.ind-cell {
  background: #1a1a2e;
  border-radius: 6px;
  padding: 8px 10px;
  text-align: center;
}
.ind-label {
  font-size: 10px;
  color: #606266;
  margin-bottom: 3px;
  text-transform: uppercase;
}
.ind-value {
  font-size: 13px;
  font-weight: 600;
  color: #c0c4cc;
  font-family: monospace;
}
.ind-value.up   { color: #f56c6c; }
.ind-value.down { color: #67c23a; }

.drawer-actions { display: flex; gap: 8px; flex-wrap: wrap; }

/* 移动端 */
@media (max-width: 480px) {
  .page-header { padding: 14px; }
  .stocks-grid { grid-template-columns: 1fr; }
  .card-mid { grid-template-columns: 140px 1fr; }
  .radar-chart { width: 140px; height: 130px; }
  .strategy-grid { grid-template-columns: 1fr; }
  .scan-summary { gap: 10px; }
}
</style>
