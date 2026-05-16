<template>
  <div class="agent-page">
    <!-- ───────────────────── 顶部操作栏 ───────────────────── -->
    <div class="page-header">
      <div class="header-left">
        <h2 class="page-title">
          <span class="title-icon">🤖</span>
          Agent 决策仪表盘
        </h2>
      </div>
      <div class="header-actions">
        <el-autocomplete
          v-model="searchKeyword"
          :fetch-suggestions="handleSearch"
          placeholder="搜索股票代码或名称，或直接输入代码如 600028.SH"
          @select="onSearchSelect"
          @keyup.enter="onSearchEnter"
          @blur="onSearchBlur"
          style="width: 280px"
          clearable
        >
          <template #default="{ item }">
            <span class="search-name">{{ item.name }}</span>
            <span class="search-symbol">{{ item.symbol }}</span>
          </template>
        </el-autocomplete>
        <el-button
          type="primary"
          :loading="analyzing"
          @click="analyzeCurrentSymbol"
          :disabled="!searchKeyword.trim()"
        >
          <template #icon><span>📊</span></template>
          {{ analyzing ? '分析中...' : '分析当前股票' }}
        </el-button>
        <span v-if="analyzing" class="hint-blink">
          Agent 正在调用工具分析，约需 30-120 秒
        </span>
        <el-button type="warning" :loading="scanning" @click="scanAll">
          <template #icon><span>🔍</span></template>
          扫描全部自选股
        </el-button>
      </div>
    </div>

    <!-- ───────────────────── 分析结果 ───────────────────── -->
    <template v-if="currentAnalysis">
      <!-- ① 核心结论卡片 ─────────────────────────────── -->
      <div class="conclusion-card" :class="`border-${currentAnalysis.action?.toLowerCase()}`">
        <div class="conclusion-top">
          <div class="conclusion-id">
            <span class="stock-name">{{ currentAnalysis.name }}</span>
            <span class="stock-symbol">{{ currentAnalysis.symbol }}</span>
            <el-tag v-if="currentAnalysis.llm_powered" type="success" size="small" effect="dark">AI驱动</el-tag>
            <el-tag v-else type="info" size="small" effect="dark">技术分析</el-tag>
          </div>
          <div class="conclusion-price">
            <span class="price-label">当前价</span>
            <span class="price-value">¥{{ numFmt(currentAnalysis.current_price) }}</span>
          </div>
        </div>

        <div class="conclusion-main">
          <div class="action-block">
            <div class="action-badge" :class="`action-${currentAnalysis.action?.toLowerCase()}`">
              {{ actionLabel(currentAnalysis.action) }}
            </div>
            <div class="confidence-wrap">
              <span class="conf-label">置信度</span>
              <el-progress
                :percentage="currentAnalysis.confidence || 0"
                :color="confidenceColor(currentAnalysis.confidence)"
                :stroke-width="10"
                style="width: 200px"
              />
            </div>
            <div class="meta-row">
              <el-tag :color="riskColor(currentAnalysis.risk_level)" effect="dark" size="small" style="border:none">
                {{ currentAnalysis.risk_level }}风险
              </el-tag>
              <el-tag type="info" size="small" effect="dark">{{ currentAnalysis.time_horizon }}</el-tag>
            </div>
          </div>

          <div class="conclusion-quote" v-if="currentAnalysis.core_conclusion?.one_sentence || currentAnalysis.summary">
            <div class="quote-mark">"</div>
            <p class="one-sentence">
              {{ currentAnalysis.core_conclusion?.one_sentence || (currentAnalysis.summary || '').slice(0, 50) }}
            </p>
            <div class="time-sensitivity" v-if="currentAnalysis.core_conclusion?.time_sensitivity">
              <span class="ts-icon">🕐</span>
              <span class="ts-text">{{ currentAnalysis.core_conclusion.time_sensitivity }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- ② 持仓 vs 无持仓 双栏建议 ─────────────────── -->
      <div class="advice-grid" v-if="currentAnalysis.core_conclusion?.position_advice">
        <div class="advice-card no-pos">
          <div class="advice-header">
            <span class="advice-icon">🆕</span>
            <span class="advice-title">无持仓者建议</span>
          </div>
          <p class="advice-text">
            {{ currentAnalysis.core_conclusion.position_advice.no_position || '—' }}
          </p>
        </div>
        <div class="advice-card has-pos">
          <div class="advice-header">
            <span class="advice-icon">💼</span>
            <span class="advice-title">有持仓者建议</span>
          </div>
          <p class="advice-text">
            {{ currentAnalysis.core_conclusion.position_advice.has_position || '—' }}
          </p>
        </div>
      </div>

      <!-- ③ 作战计划 ─────────────────────────────────── -->
      <div class="section-card battle-plan" v-if="hasBattlePlan(currentAnalysis)">
        <div class="section-header">
          <span class="section-icon">🎯</span>
          <span class="section-title">作战计划</span>
        </div>

        <!-- 价格四档 -->
        <div class="price-grid-4">
          <div class="price-card price-buy" v-if="battleBuyIdeal">
            <div class="pc-icon">🎯</div>
            <div class="pc-label">理想买点</div>
            <div class="pc-value">{{ battleBuyIdeal }}</div>
          </div>
          <div class="price-card price-secondary" v-if="battleBuySecondary">
            <div class="pc-icon">🔵</div>
            <div class="pc-label">次要买点</div>
            <div class="pc-value">{{ battleBuySecondary }}</div>
          </div>
          <div class="price-card price-stop" v-if="battleStopLoss">
            <div class="pc-icon">🛑</div>
            <div class="pc-label">止损价</div>
            <div class="pc-value">{{ battleStopLoss }}</div>
          </div>
          <div class="price-card price-profit" v-if="battleTakeProfit">
            <div class="pc-icon">🎊</div>
            <div class="pc-label">止盈目标</div>
            <div class="pc-value">{{ battleTakeProfit }}</div>
          </div>
        </div>

        <!-- 仓位 / 计划 / 风控 -->
        <div class="position-strategy" v-if="hasPositionStrategy(currentAnalysis)">
          <div class="ps-block ps-position" v-if="currentAnalysis.battle_plan?.suggested_position">
            <div class="ps-label">📐 建议仓位</div>
            <div class="ps-value-large">{{ currentAnalysis.battle_plan.suggested_position }}</div>
          </div>
          <div class="ps-block" v-if="currentAnalysis.battle_plan?.entry_plan">
            <div class="ps-label">📋 建仓计划</div>
            <div class="ps-value">{{ currentAnalysis.battle_plan.entry_plan }}</div>
          </div>
          <div class="ps-block" v-if="currentAnalysis.battle_plan?.risk_control">
            <div class="ps-label">🛡️ 风控要点</div>
            <div class="ps-value">{{ currentAnalysis.battle_plan.risk_control }}</div>
          </div>
        </div>
      </div>

      <!-- ④ 操作前检查清单 ───────────────────────────── -->
      <div class="section-card checklist-card" v-if="currentAnalysis.action_checklist?.length">
        <div class="section-header">
          <span class="section-icon">✅</span>
          <span class="section-title">操作前检查清单</span>
          <span class="checklist-count">{{ currentAnalysis.action_checklist.length }} 项</span>
        </div>
        <ul class="checklist">
          <li v-for="(item, i) in currentAnalysis.action_checklist" :key="i" class="checklist-item">
            <span class="check-box">☐</span>
            <span class="check-text">{{ item }}</span>
          </li>
        </ul>
      </div>

      <!-- ⑤ 数据视角 ─────────────────────────────────── -->
      <div class="section-card dashboard-card" v-if="currentAnalysis.data_perspective">
        <div class="section-header">
          <span class="section-icon">📊</span>
          <span class="section-title">数据视角</span>
        </div>

        <div class="dashboard-grid">
          <!-- 趋势状态 -->
          <div class="dash-block trend-block" v-if="currentAnalysis.data_perspective.trend_status">
            <div class="dash-block-title">📈 趋势状态</div>
            <div class="trend-content">
              <div class="trend-line" v-if="currentAnalysis.data_perspective.trend_status.ma_alignment">
                <span class="trend-key">均线排列</span>
                <span class="trend-val">{{ currentAnalysis.data_perspective.trend_status.ma_alignment }}</span>
              </div>
              <div class="trend-line">
                <span class="trend-key">多头排列</span>
                <span class="trend-val">
                  <span :class="currentAnalysis.data_perspective.trend_status.is_bullish ? 'bullish' : 'bearish'">
                    {{ currentAnalysis.data_perspective.trend_status.is_bullish ? '✅ 是' : '❌ 否' }}
                  </span>
                </span>
              </div>
              <div class="trend-line" v-if="currentAnalysis.data_perspective.trend_status.trend_score != null">
                <span class="trend-key">趋势评分</span>
                <span class="trend-val score">
                  {{ currentAnalysis.data_perspective.trend_status.trend_score }}/100
                </span>
              </div>
              <div class="trend-desc" v-if="currentAnalysis.data_perspective.trend_status.trend_desc">
                {{ currentAnalysis.data_perspective.trend_status.trend_desc }}
              </div>
            </div>
          </div>

          <!-- 量能分析 -->
          <div class="dash-block volume-block" v-if="currentAnalysis.data_perspective.volume_analysis">
            <div class="dash-block-title">📊 量能分析</div>
            <div class="volume-content">
              <div class="volume-ratio-wrap">
                <span class="vr-label">量比</span>
                <span class="vr-value" :class="volumeColorClass(currentAnalysis.data_perspective.volume_analysis.volume_ratio)">
                  {{ numFmt(currentAnalysis.data_perspective.volume_analysis.volume_ratio) }}
                </span>
              </div>
              <div class="volume-status" v-if="currentAnalysis.data_perspective.volume_analysis.volume_status">
                <el-tag size="small" effect="dark" type="warning">
                  {{ currentAnalysis.data_perspective.volume_analysis.volume_status }}
                </el-tag>
              </div>
              <div class="volume-meaning" v-if="currentAnalysis.data_perspective.volume_analysis.volume_meaning">
                {{ currentAnalysis.data_perspective.volume_analysis.volume_meaning }}
              </div>
            </div>
          </div>

          <!-- 指标徽章 -->
          <div class="dash-block badges-block">
            <div class="dash-block-title">⚙️ 指标状态</div>
            <div class="badges-row">
              <div class="badge-item" v-if="currentAnalysis.data_perspective.rsi_status">
                <div class="badge-label">RSI</div>
                <div class="badge-value rsi">{{ currentAnalysis.data_perspective.rsi_status }}</div>
              </div>
              <div class="badge-item" v-if="currentAnalysis.data_perspective.macd_status">
                <div class="badge-label">MACD</div>
                <div class="badge-value macd">{{ currentAnalysis.data_perspective.macd_status }}</div>
              </div>
            </div>
          </div>
        </div>

        <!-- 价格位置表 -->
        <div class="price-position-table" v-if="currentAnalysis.data_perspective.price_position">
          <div class="ppt-title">📍 价格位置</div>
          <div class="ppt-grid">
            <div class="ppt-cell" v-if="currentAnalysis.data_perspective.price_position.current_price != null">
              <div class="ppt-label">当前价</div>
              <div class="ppt-value strong">¥{{ numFmt(currentAnalysis.data_perspective.price_position.current_price) }}</div>
            </div>
            <div class="ppt-cell" v-for="ma in ['ma5','ma10','ma20','ma60']" :key="ma"
                 v-show="currentAnalysis.data_perspective.price_position[ma] != null">
              <div class="ppt-label">{{ ma.toUpperCase() }}</div>
              <div class="ppt-value">¥{{ numFmt(currentAnalysis.data_perspective.price_position[ma]) }}</div>
            </div>
            <div class="ppt-cell" v-if="currentAnalysis.data_perspective.price_position.bias_ma5 != null">
              <div class="ppt-label">MA5 乖离率</div>
              <div class="ppt-value" :class="signClass(currentAnalysis.data_perspective.price_position.bias_ma5)">
                {{ pctFmt(currentAnalysis.data_perspective.price_position.bias_ma5) }}
              </div>
            </div>
            <div class="ppt-cell" v-if="currentAnalysis.data_perspective.price_position.bias_ma20 != null">
              <div class="ppt-label">MA20 乖离率</div>
              <div class="ppt-value" :class="signClass(currentAnalysis.data_perspective.price_position.bias_ma20)">
                {{ pctFmt(currentAnalysis.data_perspective.price_position.bias_ma20) }}
              </div>
            </div>
            <div class="ppt-cell" v-if="currentAnalysis.data_perspective.price_position.bias_status">
              <div class="ppt-label">乖离状态</div>
              <div class="ppt-value">{{ currentAnalysis.data_perspective.price_position.bias_status }}</div>
            </div>
            <div class="ppt-cell" v-if="currentAnalysis.data_perspective.price_position.support_level != null">
              <div class="ppt-label">支撑位</div>
              <div class="ppt-value buy-color">¥{{ numFmt(currentAnalysis.data_perspective.price_position.support_level) }}</div>
            </div>
            <div class="ppt-cell" v-if="currentAnalysis.data_perspective.price_position.resistance_level != null">
              <div class="ppt-label">阻力位</div>
              <div class="ppt-value stop-color">¥{{ numFmt(currentAnalysis.data_perspective.price_position.resistance_level) }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- ⑥ 情报中心 ─────────────────────────────────── -->
      <div class="section-card intel-card" v-if="hasIntelligence(currentAnalysis)">
        <div class="section-header">
          <span class="section-icon">📰</span>
          <span class="section-title">情报中心</span>
        </div>

        <div class="intel-grid">
          <div class="intel-block" v-if="currentAnalysis.intelligence?.sentiment_summary">
            <div class="intel-head">💭 市场情绪</div>
            <p class="intel-text">{{ currentAnalysis.intelligence.sentiment_summary }}</p>
          </div>

          <div class="intel-block" v-if="currentAnalysis.intelligence?.earnings_outlook">
            <div class="intel-head">📊 业绩预期</div>
            <p class="intel-text">{{ currentAnalysis.intelligence.earnings_outlook }}</p>
          </div>

          <div class="intel-block alerts" v-if="currentAnalysis.intelligence?.risk_alerts?.length">
            <div class="intel-head">🚨 风险警报</div>
            <ul class="intel-list risk">
              <li v-for="(a, i) in currentAnalysis.intelligence.risk_alerts" :key="i">{{ a }}</li>
            </ul>
          </div>

          <div class="intel-block catalysts" v-if="currentAnalysis.intelligence?.positive_catalysts?.length">
            <div class="intel-head">✨ 利好催化</div>
            <ul class="intel-list catalyst">
              <li v-for="(c, i) in currentAnalysis.intelligence.positive_catalysts" :key="i">{{ c }}</li>
            </ul>
          </div>

          <div class="intel-block latest" v-if="currentAnalysis.intelligence?.latest_news">
            <div class="intel-head">📢 最新动态</div>
            <p class="intel-text">{{ currentAnalysis.intelligence.latest_news }}</p>
          </div>
        </div>
      </div>

      <!-- ⑦ 综合结论（fallback / 详细） -->
      <div class="section-card" v-if="currentAnalysis.summary">
        <div class="section-header">
          <span class="section-icon">📝</span>
          <span class="section-title">综合结论</span>
        </div>
        <p class="summary-text">{{ currentAnalysis.summary }}</p>
      </div>

      <!-- ⑧ 四个分析模块 -->
      <div class="analysis-grid">
        <div class="analysis-module" v-if="currentAnalysis.technical_analysis">
          <div class="module-header">
            <span class="module-icon">📈</span>
            <span class="module-title">技术面分析</span>
          </div>
          <p class="module-text">{{ currentAnalysis.technical_analysis }}</p>
        </div>
        <div class="analysis-module" v-if="currentAnalysis.news_analysis">
          <div class="module-header">
            <span class="module-icon">📰</span>
            <span class="module-title">消息面分析</span>
          </div>
          <p class="module-text">{{ currentAnalysis.news_analysis }}</p>
        </div>
        <div class="analysis-module" v-if="currentAnalysis.market_analysis">
          <div class="module-header">
            <span class="module-icon">🌐</span>
            <span class="module-title">大盘环境</span>
          </div>
          <p class="module-text">{{ currentAnalysis.market_analysis }}</p>
        </div>
        <div class="analysis-module" v-if="currentAnalysis.risk_analysis">
          <div class="module-header">
            <span class="module-icon">⚠️</span>
            <span class="module-title">风险提示</span>
          </div>
          <p class="module-text">{{ currentAnalysis.risk_analysis }}</p>
        </div>
      </div>

      <!-- ⑨ 三列要点 -->
      <div class="three-col-grid">
        <div class="col-card" v-if="currentAnalysis.key_points?.length">
          <div class="col-header">
            <span class="col-icon">🎯</span>
            <span class="col-title">核心要点</span>
          </div>
          <ul class="point-list">
            <li v-for="(pt, i) in currentAnalysis.key_points" :key="i">{{ pt }}</li>
          </ul>
        </div>
        <div class="col-card" v-if="currentAnalysis.catalysts?.length">
          <div class="col-header">
            <span class="col-icon">🚀</span>
            <span class="col-title">潜在催化剂</span>
          </div>
          <ul class="point-list catalyst">
            <li v-for="(c, i) in currentAnalysis.catalysts" :key="i">{{ c }}</li>
          </ul>
        </div>
        <div class="col-card" v-if="currentAnalysis.risk_factors?.length">
          <div class="col-header">
            <span class="col-icon">🛡️</span>
            <span class="col-title">主要风险</span>
          </div>
          <ul class="point-list risk">
            <li v-for="(r, i) in currentAnalysis.risk_factors" :key="i">{{ r }}</li>
          </ul>
        </div>
      </div>

      <!-- ⑩ 支撑/压力位 -->
      <div class="levels-card" v-if="currentAnalysis.support_levels?.length || currentAnalysis.resistance_levels?.length">
        <div class="levels-group" v-if="currentAnalysis.support_levels?.length">
          <span class="levels-label">📗 支撑位</span>
          <el-tag
            v-for="(lv, i) in currentAnalysis.support_levels"
            :key="i"
            color="#1a3a1a"
            style="border-color:#67c23a;color:#67c23a;margin:2px"
            effect="dark"
          >
            ¥{{ typeof lv === 'number' ? lv.toFixed(2) : lv }}
          </el-tag>
        </div>
        <div class="levels-group" v-if="currentAnalysis.resistance_levels?.length">
          <span class="levels-label">📕 压力位</span>
          <el-tag
            v-for="(lv, i) in currentAnalysis.resistance_levels"
            :key="i"
            color="#3a1a1a"
            style="border-color:#f56c6c;color:#f56c6c;margin:2px"
            effect="dark"
          >
            ¥{{ typeof lv === 'number' ? lv.toFixed(2) : lv }}
          </el-tag>
        </div>
      </div>

      <!-- ⑪ 技术指标折叠 -->
      <el-collapse v-if="currentAnalysis.indicators" class="indicators-collapse">
        <el-collapse-item name="indicators">
          <template #title>
            <span class="collapse-title">📊 技术指标详情</span>
          </template>
          <div class="indicators-panel">
            <!-- 均线 -->
            <div class="ind-group" v-if="hasAnyKey(currentAnalysis.indicators, ['ma5','ma10','ma20','ma60'])">
              <div class="ind-group-title">均线</div>
              <div class="ind-tags">
                <span v-for="key in ['ma5','ma10','ma20','ma60']" :key="key">
                  <el-tag v-if="currentAnalysis.indicators[key] != null" size="small" class="ind-tag" effect="dark" type="info">
                    {{ key.toUpperCase() }} {{ numFmt(currentAnalysis.indicators[key]) }}
                  </el-tag>
                </span>
              </div>
            </div>
            <!-- RSI -->
            <div class="ind-group" v-if="currentAnalysis.indicators.rsi14 != null">
              <div class="ind-group-title">RSI</div>
              <div class="ind-tags">
                <el-tag size="small" class="ind-tag" effect="dark"
                  :type="rsiTagType(currentAnalysis.indicators.rsi14)">
                  RSI14 {{ numFmt(currentAnalysis.indicators.rsi14) }}
                </el-tag>
              </div>
            </div>
            <!-- MACD -->
            <div class="ind-group" v-if="hasAnyKey(currentAnalysis.indicators, ['macd_dif','macd_dea','macd_hist'])">
              <div class="ind-group-title">MACD</div>
              <div class="ind-tags">
                <el-tag v-if="currentAnalysis.indicators.macd_dif != null" size="small" class="ind-tag" effect="dark"
                  :type="signTagType(currentAnalysis.indicators.macd_dif)">
                  DIF {{ numFmt(currentAnalysis.indicators.macd_dif) }}
                </el-tag>
                <el-tag v-if="currentAnalysis.indicators.macd_dea != null" size="small" class="ind-tag" effect="dark"
                  :type="signTagType(currentAnalysis.indicators.macd_dea)">
                  DEA {{ numFmt(currentAnalysis.indicators.macd_dea) }}
                </el-tag>
                <el-tag v-if="currentAnalysis.indicators.macd_hist != null" size="small" class="ind-tag" effect="dark"
                  :type="signTagType(currentAnalysis.indicators.macd_hist)">
                  柱 {{ numFmt(currentAnalysis.indicators.macd_hist) }}
                </el-tag>
              </div>
            </div>
            <!-- KDJ -->
            <div class="ind-group" v-if="hasAnyKey(currentAnalysis.indicators, ['kdj_k','kdj_d','kdj_j'])">
              <div class="ind-group-title">KDJ</div>
              <div class="ind-tags">
                <el-tag v-if="currentAnalysis.indicators.kdj_k != null" size="small" class="ind-tag" effect="dark" type="info">
                  K {{ numFmt(currentAnalysis.indicators.kdj_k) }}
                </el-tag>
                <el-tag v-if="currentAnalysis.indicators.kdj_d != null" size="small" class="ind-tag" effect="dark" type="info">
                  D {{ numFmt(currentAnalysis.indicators.kdj_d) }}
                </el-tag>
                <el-tag v-if="currentAnalysis.indicators.kdj_j != null" size="small" class="ind-tag" effect="dark"
                  :type="signTagType(currentAnalysis.indicators.kdj_j - 50)">
                  J {{ numFmt(currentAnalysis.indicators.kdj_j) }}
                </el-tag>
              </div>
            </div>
            <!-- 布林带 -->
            <div class="ind-group" v-if="hasAnyKey(currentAnalysis.indicators, ['boll_upper','boll_mid','boll_lower'])">
              <div class="ind-group-title">布林带</div>
              <div class="ind-tags">
                <el-tag v-if="currentAnalysis.indicators.boll_upper != null" size="small" class="ind-tag" effect="dark" type="danger">
                  上轨 {{ numFmt(currentAnalysis.indicators.boll_upper) }}
                </el-tag>
                <el-tag v-if="currentAnalysis.indicators.boll_mid != null" size="small" class="ind-tag" effect="dark" type="info">
                  中轨 {{ numFmt(currentAnalysis.indicators.boll_mid) }}
                </el-tag>
                <el-tag v-if="currentAnalysis.indicators.boll_lower != null" size="small" class="ind-tag" effect="dark" type="success">
                  下轨 {{ numFmt(currentAnalysis.indicators.boll_lower) }}
                </el-tag>
              </div>
            </div>
            <!-- 涨跌幅 -->
            <div class="ind-group" v-if="hasAnyKey(currentAnalysis.indicators, ['change_1d','change_5d','change_10d','change_20d','change_60d'])">
              <div class="ind-group-title">各周期涨跌幅</div>
              <div class="ind-tags">
                <span v-for="[key, label] in [['change_1d','1日'],['change_5d','5日'],['change_10d','10日'],['change_20d','20日'],['change_60d','60日']]" :key="key">
                  <el-tag v-if="currentAnalysis.indicators[key] != null" size="small" class="ind-tag" effect="dark"
                    :type="signTagType(currentAnalysis.indicators[key])">
                    {{ label }} {{ pctFmt(currentAnalysis.indicators[key]) }}
                  </el-tag>
                </span>
              </div>
            </div>
            <!-- 区间位置 -->
            <div class="ind-group" v-if="hasAnyKey(currentAnalysis.indicators, ['range_20d_high','range_20d_low','range_60d_high','range_60d_low'])">
              <div class="ind-group-title">区间位置</div>
              <div class="ind-tags">
                <template v-if="currentAnalysis.indicators.range_20d_high != null">
                  <el-tag size="small" class="ind-tag" effect="dark" type="info">
                    20日高 {{ numFmt(currentAnalysis.indicators.range_20d_high) }}
                  </el-tag>
                  <el-tag size="small" class="ind-tag" effect="dark" type="info">
                    20日低 {{ numFmt(currentAnalysis.indicators.range_20d_low) }}
                  </el-tag>
                  <el-tag v-if="currentAnalysis.indicators.position_20d != null" size="small" class="ind-tag" effect="dark"
                    :type="posTagType(currentAnalysis.indicators.position_20d)">
                    20日位置 {{ pctFmt(currentAnalysis.indicators.position_20d) }}
                  </el-tag>
                </template>
                <template v-if="currentAnalysis.indicators.range_60d_high != null">
                  <el-tag size="small" class="ind-tag" effect="dark" type="info">
                    60日高 {{ numFmt(currentAnalysis.indicators.range_60d_high) }}
                  </el-tag>
                  <el-tag size="small" class="ind-tag" effect="dark" type="info">
                    60日低 {{ numFmt(currentAnalysis.indicators.range_60d_low) }}
                  </el-tag>
                  <el-tag v-if="currentAnalysis.indicators.position_60d != null" size="small" class="ind-tag" effect="dark"
                    :type="posTagType(currentAnalysis.indicators.position_60d)">
                    60日位置 {{ pctFmt(currentAnalysis.indicators.position_60d) }}
                  </el-tag>
                </template>
              </div>
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>

      <!-- ⑫ 操作按钮栏 -->
      <div class="action-bar">
        <el-button type="success" @click="addPosition(currentAnalysis)">
          📋 录入持仓
        </el-button>
        <el-button type="warning" @click="setAlert(currentAnalysis)">
          🔔 设置止损提醒
        </el-button>
        <el-button type="primary" @click="viewKline(currentAnalysis)">
          📉 查看K线
        </el-button>
        <el-button @click="currentAnalysis = null" style="margin-left:auto">
          ✕ 关闭
        </el-button>
      </div>
    </template>

    <!-- ───────────────────── 扫描结果 ───────────────────── -->
    <template v-else-if="scanResults.length > 0">
      <div class="section-header-row">
        <span class="section-heading">扫描结果 — 按机会排序</span>
        <el-tag size="small" type="info">{{ scanResults.length }} 只</el-tag>
        <el-button size="small" text @click="scanResults = []" style="margin-left:auto">清除</el-button>
      </div>
      <div class="scan-grid">
        <div
          v-for="r in scanResults"
          :key="r.symbol"
          class="scan-card"
          :class="`border-${r.action?.toLowerCase()}`"
          @click="showDetail(r)"
        >
          <div class="sc-header">
            <span class="sc-name">{{ r.name }}</span>
            <el-tag :type="actionTagType(r.action)" size="small" effect="dark">
              {{ actionLabel(r.action) }}
            </el-tag>
          </div>
          <div class="sc-price">¥{{ r.current_price?.toFixed(2) }}</div>
          <div class="sc-conf-row">
            <el-progress
              :percentage="r.confidence"
              :color="confidenceColor(r.confidence)"
              :stroke-width="5"
              :show-text="false"
            />
            <span class="sc-conf-text">{{ r.confidence }}%</span>
          </div>
          <div class="sc-buy" v-if="r.buy_price_low">
            买入 ¥{{ r.buy_price_low?.toFixed(2) }}–{{ r.buy_price_high?.toFixed(2) }}
          </div>
          <p class="sc-summary">{{ ((r.core_conclusion?.one_sentence) || r.summary || r.reason || '').slice(0, 50) }}…</p>
          <div class="sc-meta">
            <span>{{ r.risk_level }}风险</span>
            <span>{{ r.time_horizon }}</span>
          </div>
        </div>
      </div>
    </template>

    <!-- ───────────────────── 历史缓存 ───────────────────── -->
    <template v-else>
      <div v-if="cachedAnalyses.length > 0" class="cache-section">
        <div class="section-header-row">
          <span class="section-heading">历史分析缓存</span>
        </div>
        <el-table :data="cachedAnalyses" size="small" class="cache-table">
          <el-table-column label="股票" min-width="90">
            <template #default="{ row }">
              <span class="tbl-name">{{ row.name || row.result?.name }}</span>
            </template>
          </el-table-column>
          <el-table-column label="代码" width="100">
            <template #default="{ row }">
              <span class="tbl-symbol">{{ row.symbol }}</span>
            </template>
          </el-table-column>
          <el-table-column label="建议" width="80">
            <template #default="{ row }">
              <el-tag :type="actionTagType(row.result?.action)" size="small" effect="dark">
                {{ actionLabel(row.result?.action) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="置信度" width="80">
            <template #default="{ row }">
              <span :style="{ color: confidenceColor(row.result?.confidence) }">
                {{ row.result?.confidence }}%
              </span>
            </template>
          </el-table-column>
          <el-table-column label="买入区间" min-width="150">
            <template #default="{ row }">
              <span class="buy-color">
                ¥{{ row.result?.buy_price_low?.toFixed(2) }} – ¥{{ row.result?.buy_price_high?.toFixed(2) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="分析时间" width="150">
            <template #default="{ row }">{{ row.updated_at?.slice(0, 16) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="80" fixed="right">
            <template #default="{ row }">
              <el-button size="small" type="primary" text @click="showDetail(row.result)">详情</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <div v-else class="empty-state">
        <div class="empty-icon">🤖</div>
        <div class="empty-text">搜索股票后点击「分析当前股票」，或扫描全部自选股</div>
      </div>
    </template>

    <!-- ───────────────────── 录入持仓弹窗 ───────────────────── -->
    <el-dialog v-model="showPositionDialog" title="录入持仓" width="420px" class="dark-dialog">
      <el-form :model="positionForm" label-width="90px">
        <el-form-item label="股票">
          <span>{{ positionForm.name }}（{{ positionForm.symbol }}）</span>
        </el-form-item>
        <el-form-item label="持仓数量">
          <el-input-number v-model="positionForm.quantity" :min="100" :step="100" style="width:100%" />
        </el-form-item>
        <el-form-item label="买入均价">
          <el-input-number v-model="positionForm.avg_cost" :precision="2" :step="0.1" style="width:100%" />
        </el-form-item>
        <el-form-item label="止损比例">
          <div style="display:flex;align-items:center;gap:8px;width:100%">
            <el-input-number
              v-model="positionForm.stop_loss_pct"
              :precision="2"
              :step="0.01"
              :min="0.01"
              :max="0.5"
              style="flex:1"
            />
            <span style="color:#909399;font-size:13px;white-space:nowrap">
              {{ (positionForm.stop_loss_pct * 100).toFixed(0) }}%
            </span>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showPositionDialog = false">取消</el-button>
        <el-button type="primary" @click="confirmPosition">确认录入</el-button>
      </template>
    </el-dialog>
  </div>
</template>


<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api.js'

const route = useRoute()
const router = useRouter()

const searchKeyword = ref('')
const currentSymbol = ref('')
const currentName = ref('')
const analyzing = ref(false)
const scanning = ref(false)
const currentAnalysis = ref(null)
const scanResults = ref([])
const cachedAnalyses = ref([])
const showPositionDialog = ref(false)
const positionForm = ref({
  symbol: '',
  name: '',
  quantity: 100,
  avg_cost: 0,
  stop_loss_pct: 0.08,
})

// ─── 作战计划：fallback 计算 ─────────────────────────────
const battleBuyIdeal = computed(() => {
  const a = currentAnalysis.value
  if (!a) return ''
  if (a.battle_plan?.ideal_buy) return a.battle_plan.ideal_buy
  if (a.buy_price_low != null && a.buy_price_high != null) {
    return `¥${numFmt(a.buy_price_low)} ~ ¥${numFmt(a.buy_price_high)}`
  }
  return ''
})

const battleBuySecondary = computed(() => {
  const a = currentAnalysis.value
  return a?.battle_plan?.secondary_buy || ''
})

const battleStopLoss = computed(() => {
  const a = currentAnalysis.value
  if (!a) return ''
  if (a.battle_plan?.stop_loss) return a.battle_plan.stop_loss
  if (a.stop_loss != null) return `¥${numFmt(a.stop_loss)}`
  return ''
})

const battleTakeProfit = computed(() => {
  const a = currentAnalysis.value
  if (!a) return ''
  if (a.battle_plan?.take_profit) return a.battle_plan.take_profit
  if (a.take_profit != null) return `¥${numFmt(a.take_profit)}`
  return ''
})

function hasBattlePlan(a) {
  if (!a) return false
  return !!(
    a.battle_plan?.ideal_buy || a.battle_plan?.secondary_buy ||
    a.battle_plan?.stop_loss || a.battle_plan?.take_profit ||
    a.battle_plan?.suggested_position || a.battle_plan?.entry_plan ||
    a.battle_plan?.risk_control ||
    a.buy_price_low != null || a.stop_loss != null || a.take_profit != null
  )
}

function hasPositionStrategy(a) {
  if (!a?.battle_plan) return false
  const bp = a.battle_plan
  return !!(bp.suggested_position || bp.entry_plan || bp.risk_control)
}

function hasIntelligence(a) {
  const i = a?.intelligence
  if (!i) return false
  return !!(
    i.sentiment_summary || i.earnings_outlook || i.latest_news ||
    (Array.isArray(i.risk_alerts) && i.risk_alerts.length) ||
    (Array.isArray(i.positive_catalysts) && i.positive_catalysts.length)
  )
}

// ─── 搜索 ────────────────────────────────────────────
async function handleSearch(query, cb) {
  if (!query || query.length < 1) return cb([])
  try {
    const results = await api.search(query)
    cb((results || []).map(r => ({ ...r, value: r.name })))
  } catch {
    cb([])
  }
}

function onSearchSelect(item) {
  currentSymbol.value = item.symbol
  currentName.value = item.name
  searchKeyword.value = item.name
}

function onSearchEnter() {
  _resolveFromKeyword()
}

function onSearchBlur() {
  _resolveFromKeyword()
}

function _resolveFromKeyword() {
  const kw = searchKeyword.value.trim().toUpperCase()
  if (!kw) return
  if (/^\d{6}\.(SH|SZ|BJ)$/.test(kw)) {
    currentSymbol.value = kw
    currentName.value = kw
    return
  }
  if (/^\d{6}$/.test(kw)) {
    const exchange = kw.startsWith('6') || kw.startsWith('9') ? 'SH' : 'SZ'
    currentSymbol.value = `${kw}.${exchange}`
    currentName.value = currentSymbol.value
    return
  }
}

// ─── 分析 ────────────────────────────────────────────
async function analyzeCurrentSymbol() {
  if (!currentSymbol.value) {
    _resolveFromKeyword()
  }
  const symbol = currentSymbol.value || searchKeyword.value.trim().toUpperCase()
  if (!symbol) {
    ElMessage.warning('请先搜索并选择股票，或直接输入股票代码（如 600028.SH）')
    return
  }
  if (!currentSymbol.value) {
    currentSymbol.value = symbol
    currentName.value = symbol
  }

  analyzing.value = true
  currentAnalysis.value = null
  scanResults.value = []

  const progressMsg = ElMessage({
    message: 'Agent 正在分析（拉取行情、计算指标、识别形态、抓取新闻、综合推理）...',
    type: 'info',
    duration: 0,
    showClose: false,
  })

  try {
    const result = await api.analyze(currentSymbol.value)
    currentAnalysis.value = result
    ElMessage.success('分析完成')
  } catch (e) {
    if (e.message?.includes('timeout')) {
      ElMessage.error('分析超时（Agent 需要调用多个工具，请稍后重试或检查网络）')
    } else {
      ElMessage.error(e.message)
    }
  } finally {
    analyzing.value = false
    progressMsg?.close?.()
  }
}

// ─── 扫描 ────────────────────────────────────────────
async function scanAll() {
  scanning.value = true
  currentAnalysis.value = null
  scanResults.value = []
  try {
    const res = await api.scan()
    scanResults.value = res.results || []
    ElMessage.success(`扫描完成，共 ${scanResults.value.length} 只`)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    scanning.value = false
  }
}

// ─── 详情 ────────────────────────────────────────────
function showDetail(r) {
  currentAnalysis.value = r
  scanResults.value = []
}

// ─── 持仓 ────────────────────────────────────────────
function addPosition(analysis) {
  positionForm.value = {
    symbol: analysis.symbol,
    name: analysis.name,
    quantity: 100,
    avg_cost: analysis.buy_price_low || analysis.current_price || 0,
    stop_loss_pct: 0.08,
  }
  showPositionDialog.value = true
}

async function confirmPosition() {
  try {
    await api.upsertPosition(positionForm.value)
    ElMessage.success('持仓已录入')
    showPositionDialog.value = false
  } catch (e) {
    ElMessage.error(e.message)
  }
}

// ─── 提醒 ────────────────────────────────────────────
async function setAlert(analysis) {
  try {
    await api.createAlert({
      symbol: analysis.symbol,
      name: analysis.name,
      alert_type: 'price_below',
      target_price: analysis.stop_loss,
      message: `${analysis.name} 止损价提醒`,
    })
    ElMessage.success('止损提醒已设置')
  } catch (e) {
    ElMessage.error(e.message)
  }
}

// ─── K线 ────────────────────────────────────────────
function viewKline(analysis) {
  router.push({ path: '/market', query: { symbol: analysis.symbol, name: analysis.name } })
}

// ─── 格式化 ──────────────────────────────────────────
function actionLabel(action) {
  return { BUY: '买入', SELL: '卖出', HOLD: '持有', WATCH: '关注' }[action] || action || '—'
}

function actionTagType(action) {
  return { BUY: 'success', SELL: 'danger', HOLD: 'info', WATCH: 'warning' }[action] || 'info'
}

function confidenceColor(v) {
  if (v >= 70) return '#67c23a'
  if (v >= 50) return '#e6a23c'
  return '#909399'
}

function riskColor(level) {
  return { '低': '#1a3a1a', '中': '#3a2a0a', '高': '#3a1a1a' }[level] || '#2a2a4a'
}

function rsiTagType(v) {
  if (v >= 70) return 'danger'
  if (v <= 30) return 'success'
  return 'info'
}

function signTagType(v) {
  if (v > 0) return 'success'
  if (v < 0) return 'danger'
  return 'info'
}

function signClass(v) {
  if (v == null) return ''
  const n = typeof v === 'number' ? v : parseFloat(v)
  if (n > 0) return 'positive'
  if (n < 0) return 'negative'
  return ''
}

function posTagType(v) {
  if (v >= 0.7) return 'danger'
  if (v <= 0.3) return 'success'
  return 'warning'
}

function volumeColorClass(v) {
  if (v == null) return ''
  const n = typeof v === 'number' ? v : parseFloat(v)
  if (n >= 2) return 'volume-high'
  if (n >= 1.5) return 'volume-mid'
  if (n < 0.7) return 'volume-low'
  return ''
}

function numFmt(v) {
  if (v == null) return '—'
  return typeof v === 'number' ? v.toFixed(2) : v
}

function pctFmt(v) {
  if (v == null) return '—'
  const n = typeof v === 'number' ? v : parseFloat(v)
  const pct = Math.abs(n) <= 1 ? n * 100 : n
  return (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%'
}

function hasAnyKey(obj, keys) {
  return obj && keys.some(k => obj[k] != null)
}

// ─── 初始化 ──────────────────────────────────────────
onMounted(async () => {
  if (route.query.symbol) {
    currentSymbol.value = route.query.symbol
    currentName.value = route.query.name || route.query.symbol
    searchKeyword.value = currentName.value
    await analyzeCurrentSymbol()
  }
  try {
    cachedAnalyses.value = await api.analysisCache()
  } catch {}
})
</script>


<style scoped>
/* ────────────── 页面基础 ────────────── */
.agent-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding-bottom: 40px;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.hint-blink {
  font-size: 12px;
  color: #909399;
  animation: blink 1.5s infinite;
}

/* ────────────── 顶部操作栏 ────────────── */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  padding: 16px 20px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 10px;
}

.page-title {
  font-size: 20px;
  font-weight: 700;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  color: #e0e0e0;
}

.title-icon { font-size: 22px; }

.header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.search-name { font-size: 14px; }
.search-symbol { color: #909399; margin-left: 8px; font-size: 12px; }

/* ────────────── ① 核心结论卡片 ────────────── */
.conclusion-card {
  background: linear-gradient(135deg, #1a1a2e 0%, #1d1d36 100%);
  border: 1px solid #2a2a4a;
  border-left-width: 4px;
  border-radius: 12px;
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.border-buy   { border-left-color: #67c23a; }
.border-sell  { border-left-color: #f56c6c; }
.border-hold  { border-left-color: #909399; }
.border-watch { border-left-color: #e6a23c; }

.conclusion-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  flex-wrap: wrap;
}

.conclusion-id {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.stock-name {
  font-size: 22px;
  font-weight: 700;
  color: #e0e0e0;
}

.stock-symbol {
  font-size: 13px;
  color: #909399;
  font-family: monospace;
}

.conclusion-price {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
}

.price-label {
  font-size: 11px;
  color: #606266;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.price-value {
  font-size: 30px;
  font-weight: 700;
  color: #e0e0e0;
  letter-spacing: -0.5px;
}

.conclusion-main {
  display: flex;
  gap: 28px;
  align-items: stretch;
  flex-wrap: wrap;
}

.action-block {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  min-width: 220px;
}

.action-badge {
  font-size: 38px;
  font-weight: 800;
  letter-spacing: 2px;
  padding: 10px 24px;
  border-radius: 10px;
  line-height: 1;
}

.action-buy   { color: #67c23a; background: rgba(103,194,58,0.12); box-shadow: 0 0 24px rgba(103,194,58,0.15); }
.action-sell  { color: #f56c6c; background: rgba(245,108,108,0.12); box-shadow: 0 0 24px rgba(245,108,108,0.15); }
.action-hold  { color: #909399; background: rgba(144,147,153,0.12); }
.action-watch { color: #e6a23c; background: rgba(230,162,60,0.12); box-shadow: 0 0 24px rgba(230,162,60,0.15); }

.confidence-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
}

.conf-label { font-size: 12px; color: #909399; white-space: nowrap; }

.meta-row { display: flex; gap: 8px; flex-wrap: wrap; justify-content: center; }

.conclusion-quote {
  flex: 1;
  min-width: 280px;
  background: rgba(64, 158, 255, 0.04);
  border: 1px solid rgba(64, 158, 255, 0.15);
  border-radius: 8px;
  padding: 18px 22px;
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.quote-mark {
  position: absolute;
  top: 4px;
  left: 12px;
  font-size: 36px;
  color: rgba(64, 158, 255, 0.25);
  line-height: 1;
  font-family: serif;
}

.one-sentence {
  font-size: 18px;
  font-weight: 600;
  color: #e0e0e0;
  line-height: 1.6;
  margin: 0 0 10px 0;
  padding-left: 4px;
}

.time-sensitivity {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #e6a23c;
  padding-left: 4px;
}

.ts-icon { font-size: 13px; }

/* ────────────── ② 持仓双栏 ────────────── */
.advice-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

@media (max-width: 768px) {
  .advice-grid { grid-template-columns: 1fr; }
}

.advice-card {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 10px;
  padding: 16px 20px;
}

.advice-card.no-pos { border-left: 3px solid #67c23a; }
.advice-card.has-pos { border-left: 3px solid #409eff; }

.advice-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.advice-icon { font-size: 18px; }

.advice-title {
  font-size: 14px;
  font-weight: 600;
  color: #c0c4cc;
}

.advice-text {
  font-size: 14px;
  line-height: 1.7;
  color: #c0c4cc;
  margin: 0;
  white-space: pre-wrap;
}

/* ────────────── 通用 section 卡片 ────────────── */
.section-card {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 10px;
  padding: 18px 20px;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
}

.section-icon { font-size: 16px; }

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #c0c4cc;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* ────────────── ③ 作战计划 ────────────── */
.battle-plan {}

.price-grid-4 {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
  margin-bottom: 14px;
}

@media (max-width: 900px) {
  .price-grid-4 { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 480px) {
  .price-grid-4 { grid-template-columns: 1fr; }
}

.price-card {
  background: #16162a;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  padding: 14px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  position: relative;
  overflow: hidden;
}

.price-card::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, transparent 0%, rgba(255,255,255,0.02) 100%);
  pointer-events: none;
}

.price-card.price-buy       { border-left: 3px solid #67c23a; }
.price-card.price-secondary { border-left: 3px solid #409eff; }
.price-card.price-stop      { border-left: 3px solid #f56c6c; }
.price-card.price-profit    { border-left: 3px solid #e6a23c; }

.pc-icon { font-size: 18px; }

.pc-label {
  font-size: 11px;
  color: #909399;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-weight: 600;
}

.pc-value {
  font-size: 15px;
  font-weight: 600;
  color: #e0e0e0;
  line-height: 1.5;
  word-break: break-all;
}

.price-card.price-buy       .pc-value { color: #67c23a; }
.price-card.price-secondary .pc-value { color: #409eff; }
.price-card.price-stop      .pc-value { color: #f56c6c; }
.price-card.price-profit    .pc-value { color: #e6a23c; }

.position-strategy {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 10px;
  padding-top: 12px;
  border-top: 1px dashed #2a2a4a;
}

@media (max-width: 900px) {
  .position-strategy { grid-template-columns: 1fr; }
}

.ps-block {
  background: #16162a;
  border-radius: 8px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.ps-block.ps-position {
  background: linear-gradient(135deg, rgba(64,158,255,0.08), rgba(64,158,255,0.02));
  border: 1px solid rgba(64,158,255,0.3);
}

.ps-label {
  font-size: 12px;
  color: #909399;
  font-weight: 600;
}

.ps-value {
  font-size: 13px;
  color: #c0c4cc;
  line-height: 1.6;
  white-space: pre-wrap;
}

.ps-value-large {
  font-size: 22px;
  font-weight: 700;
  color: #409eff;
  letter-spacing: 0.5px;
}

/* ────────────── ④ 检查清单 ────────────── */
.checklist-card {}

.checklist-count {
  margin-left: auto;
  font-size: 12px;
  color: #909399;
  background: #16162a;
  padding: 2px 10px;
  border-radius: 12px;
}

.checklist {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.checklist-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  background: #16162a;
  border: 1px solid #2a2a4a;
  border-radius: 6px;
  padding: 10px 14px;
  transition: border-color 0.15s;
}

.checklist-item:hover {
  border-color: #409eff;
}

.check-box {
  font-size: 16px;
  color: #909399;
  line-height: 1.5;
  flex-shrink: 0;
}

.check-text {
  font-size: 13px;
  color: #c0c4cc;
  line-height: 1.6;
}

/* ────────────── ⑤ 数据视角仪表盘 ────────────── */
.dashboard-card {}

.dashboard-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 14px;
}

@media (max-width: 900px) {
  .dashboard-grid { grid-template-columns: 1fr; }
}

.dash-block {
  background: #16162a;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.dash-block-title {
  font-size: 12px;
  color: #909399;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.trend-content {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.trend-line {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
}

.trend-key { color: #909399; }
.trend-val { color: #e0e0e0; font-weight: 500; }
.trend-val.score { color: #409eff; font-family: monospace; }

.bullish { color: #67c23a; }
.bearish { color: #f56c6c; }

.trend-desc {
  margin-top: 4px;
  font-size: 12px;
  color: #c0c4cc;
  line-height: 1.5;
  padding-top: 8px;
  border-top: 1px dashed #2a2a4a;
}

.volume-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.volume-ratio-wrap {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.vr-label { font-size: 12px; color: #909399; }
.vr-value {
  font-size: 24px;
  font-weight: 700;
  font-family: monospace;
  color: #e0e0e0;
}

.vr-value.volume-high { color: #f56c6c; }
.vr-value.volume-mid  { color: #e6a23c; }
.vr-value.volume-low  { color: #909399; }

.volume-meaning {
  font-size: 12px;
  color: #c0c4cc;
  line-height: 1.5;
}

.badges-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.badge-item {
  flex: 1;
  min-width: 90px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 6px;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.badge-label {
  font-size: 11px;
  color: #606266;
  font-weight: 600;
}

.badge-value {
  font-size: 13px;
  font-weight: 600;
  color: #e0e0e0;
}

.badge-value.rsi  { color: #67c23a; }
.badge-value.macd { color: #409eff; }

/* 价格位置表 */
.price-position-table {
  background: #16162a;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  padding: 14px 16px;
}

.ppt-title {
  font-size: 12px;
  color: #909399;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 10px;
}

.ppt-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 10px;
}

.ppt-cell {
  background: #1a1a2e;
  border-radius: 6px;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.ppt-label {
  font-size: 11px;
  color: #606266;
  text-transform: uppercase;
  letter-spacing: 0.4px;
}

.ppt-value {
  font-size: 14px;
  color: #c0c4cc;
  font-family: monospace;
  font-weight: 500;
}

.ppt-value.strong { color: #e0e0e0; font-weight: 700; font-size: 15px; }
.ppt-value.positive { color: #67c23a; }
.ppt-value.negative { color: #f56c6c; }

.buy-color   { color: #67c23a; }
.stop-color  { color: #f56c6c; }
.profit-color { color: #e6a23c; }

/* ────────────── ⑥ 情报中心 ────────────── */
.intel-card {}

.intel-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

@media (max-width: 900px) {
  .intel-grid { grid-template-columns: 1fr; }
}

.intel-block {
  background: #16162a;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.intel-block.alerts    { border-left: 3px solid #f56c6c; }
.intel-block.catalysts { border-left: 3px solid #67c23a; }
.intel-block.latest    { grid-column: 1 / -1; border-left: 3px solid #409eff; }

.intel-head {
  font-size: 13px;
  color: #c0c4cc;
  font-weight: 600;
}

.intel-text {
  font-size: 13px;
  line-height: 1.7;
  color: #c0c4cc;
  margin: 0;
  white-space: pre-wrap;
}

.intel-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.intel-list li {
  font-size: 13px;
  color: #c0c4cc;
  line-height: 1.6;
  padding-left: 16px;
  position: relative;
}

.intel-list.risk li::before {
  content: '⚠';
  position: absolute;
  left: 0;
  color: #f56c6c;
}

.intel-list.catalyst li::before {
  content: '◆';
  position: absolute;
  left: 0;
  color: #67c23a;
}

/* ────────────── 综合结论 ────────────── */
.summary-text {
  font-size: 15px;
  line-height: 1.8;
  color: #c0c4cc;
  margin: 0;
  white-space: pre-wrap;
}

/* ────────────── 四模块网格 ────────────── */
.analysis-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

@media (max-width: 768px) {
  .analysis-grid { grid-template-columns: 1fr; }
}

.analysis-module {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 10px;
  padding: 16px 18px;
}

.module-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
}

.module-icon { font-size: 15px; }
.module-title {
  font-size: 13px;
  font-weight: 600;
  color: #909399;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.module-text {
  font-size: 14px;
  line-height: 1.75;
  color: #c0c4cc;
  margin: 0;
  white-space: pre-wrap;
}

/* ────────────── 三列信息 ────────────── */
.three-col-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

@media (max-width: 900px) {
  .three-col-grid { grid-template-columns: 1fr; }
}

.col-card {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 10px;
  padding: 16px 18px;
}

.col-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
}

.col-icon { font-size: 15px; }
.col-title {
  font-size: 13px;
  font-weight: 600;
  color: #909399;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.point-list {
  padding-left: 18px;
  margin: 0;
}

.point-list li {
  font-size: 13px;
  color: #c0c4cc;
  line-height: 1.8;
}

.point-list.catalyst li::marker { color: #67c23a; }
.point-list.risk li::marker { color: #f56c6c; }

/* ────────────── 支撑/压力位 ────────────── */
.levels-card {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 10px;
  padding: 14px 18px;
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
}

.levels-group {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.levels-label {
  font-size: 13px;
  font-weight: 600;
  color: #909399;
  white-space: nowrap;
}

/* ────────────── 技术指标折叠 ────────────── */
.indicators-collapse {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 10px;
  overflow: hidden;
}

.indicators-collapse :deep(.el-collapse-item__header) {
  background: #1a1a2e;
  border-bottom-color: #2a2a4a;
  padding: 0 18px;
  height: 48px;
}

.indicators-collapse :deep(.el-collapse-item__wrap) {
  background: #16162a;
  border-bottom: none;
}

.indicators-collapse :deep(.el-collapse-item__content) {
  padding: 16px 18px;
}

.collapse-title {
  font-size: 14px;
  font-weight: 600;
  color: #c0c4cc;
}

.indicators-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.ind-group-title {
  font-size: 11px;
  color: #606266;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 6px;
}

.ind-tags { display: flex; flex-wrap: wrap; gap: 4px; }

.ind-tag {
  font-family: monospace;
  font-size: 12px;
}

/* ────────────── 操作按钮栏 ────────────── */
.action-bar {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
  padding: 14px 18px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 10px;
}

/* ────────────── 扫描结果 ────────────── */
.section-header-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 4px;
}

.section-heading {
  font-size: 14px;
  font-weight: 600;
  color: #909399;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.scan-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}

.scan-card {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-left-width: 3px;
  border-radius: 8px;
  padding: 14px;
  cursor: pointer;
  transition: border-color 0.2s, transform 0.15s;
}

.scan-card:hover {
  border-color: #409eff;
  transform: translateY(-2px);
}

.sc-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.sc-name { font-weight: 600; font-size: 14px; color: #e0e0e0; }

.sc-price {
  font-size: 22px;
  font-weight: 700;
  color: #e0e0e0;
  margin-bottom: 8px;
}

.sc-conf-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.sc-conf-text { font-size: 11px; color: #909399; white-space: nowrap; }

.sc-buy {
  font-size: 12px;
  color: #67c23a;
  margin-bottom: 6px;
}

.sc-summary {
  font-size: 12px;
  color: #909399;
  line-height: 1.5;
  margin: 0 0 6px;
}

.sc-meta {
  display: flex;
  gap: 10px;
  font-size: 11px;
  color: #606266;
}

/* ────────────── 历史缓存 ────────────── */
.cache-section {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 10px;
  padding: 16px 18px;
}

.cache-table :deep(.el-table) { background: transparent; }
.cache-table :deep(.el-table tr) { background: transparent; }

.tbl-name { font-weight: 500; color: #e0e0e0; }
.tbl-symbol { font-family: monospace; color: #909399; font-size: 12px; }

/* ────────────── 空状态 ────────────── */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 60px 20px;
  background: #1a1a2e;
  border: 1px dashed #2a2a4a;
  border-radius: 10px;
}

.empty-icon { font-size: 48px; opacity: 0.5; }
.empty-text { font-size: 14px; color: #606266; text-align: center; }

/* ────────────── 弹窗 ────────────── */
.dark-dialog :deep(.el-dialog) {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
}

.dark-dialog :deep(.el-dialog__header) {
  border-bottom: 1px solid #2a2a4a;
}
</style>
