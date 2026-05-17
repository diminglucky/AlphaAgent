<template>
  <div class="market-page">
    <!-- 左侧：自选股 -->
    <div class="sidebar">
      <div class="sidebar-header">
        <span>自选股</span>
        <el-button size="small" type="primary" :icon="Plus" @click="showAddDialog = true" circle />
      </div>

      <div class="watchlist">
        <div
          v-for="item in watchlist"
          :key="item.symbol"
          class="watchlist-item"
          :class="{ active: currentSymbol === item.symbol }"
          @click="selectSymbol(item.symbol, item.name)"
        >
          <div class="wl-left">
            <div class="wl-name">{{ item.name }}</div>
            <div class="wl-symbol">{{ item.symbol }}</div>
          </div>
          <div class="wl-right">
            <div class="wl-price" :class="pctClass(item.change_pct)">
              {{ item.price > 0 ? item.price.toFixed(2) : '--' }}
            </div>
            <div class="wl-pct" :class="pctClass(item.change_pct)">
              {{ formatPct(item.change_pct) }}
            </div>
          </div>
          <el-button
            class="wl-del"
            size="small"
            type="danger"
            :icon="Delete"
            circle
            plain
            @click.stop="removeFromWatchlist(item.symbol)"
          />
        </div>
        <div v-if="watchlist.length === 0" class="empty-tip">
          点击 + 添加自选股
        </div>
      </div>
    </div>

    <!-- 右侧主区域 -->
    <div class="main-panel">
      <!-- 搜索栏 -->
      <div class="search-bar">
        <el-autocomplete
          v-model="searchKeyword"
          :fetch-suggestions="handleSearch"
          placeholder="搜索股票代码或名称..."
          @select="onSearchSelect"
          style="width:300px"
          clearable
        >
          <template #default="{ item }">
            <span>{{ item.name }}</span>
            <span style="color:#909399;margin-left:8px;font-size:12px">{{ item.symbol }}</span>
          </template>
        </el-autocomplete>
      </div>

      <!-- 未选股票时的提示 -->
      <div v-if="!currentSymbol" class="empty-state">
        <div class="empty-icon">📈</div>
        <div>从左侧选择股票，或搜索股票代码</div>
      </div>

      <!-- 行情头部 -->
      <template v-else>
        <div class="quote-header" v-if="quote">
          <div class="qh-top">
            <div>
              <div class="quote-name">
                {{ quote.name }}
                <span class="quote-symbol">{{ currentSymbol }}</span>
              </div>
              <div class="quote-price" :class="pctClass(quote.change_pct)">
                {{ quote.price?.toFixed(2) }}
              </div>
              <div class="quote-change" :class="pctClass(quote.change_pct)">
                {{ quote.change > 0 ? '+' : '' }}{{ quote.change?.toFixed(2) }}
                （{{ formatPct(quote.change_pct) }}）
              </div>
            </div>
            <div class="quote-actions">
              <el-button type="success" size="small" @click="addToWatchlist">+ 自选</el-button>
              <el-button type="primary" size="small" @click="goAnalyze">Agent分析</el-button>
              <el-button size="small" @click="showAlertDialog = true">🔔 设置提醒</el-button>
            </div>
          </div>
          <div class="quote-meta">
            <span>今开 <b>{{ quote.open?.toFixed(2) }}</b></span>
            <span>最高 <b class="up">{{ quote.high?.toFixed(2) }}</b></span>
            <span>最低 <b class="down">{{ quote.low?.toFixed(2) }}</b></span>
            <span>昨收 <b>{{ quote.prev_close?.toFixed(2) }}</b></span>
            <span>换手 <b>{{ quote.turnover_rate?.toFixed(2) }}%</b></span>
            <span>PE <b>{{ quote.pe_ratio?.toFixed(1) }}</b></span>
            <span>PB <b>{{ quote.pb_ratio?.toFixed(2) }}</b></span>
          </div>
        </div>
        <div v-else class="loading-tip">
          <el-icon class="is-loading"><Loading /></el-icon> 加载行情中...
        </div>

        <!-- K线图 -->
        <div class="kline-card">
          <div class="kline-toolbar">
            <!-- 周期切换 -->
            <el-radio-group v-model="klinePeriod" size="small" @change="loadKline">
              <el-radio-button value="daily">日K</el-radio-button>
              <el-radio-button value="weekly">周K</el-radio-button>
              <el-radio-button value="monthly">月K</el-radio-button>
            </el-radio-group>

            <el-divider direction="vertical" />

            <!-- 视图切换 -->
            <el-button-group size="small">
              <el-button
                :type="chartView === 'both' ? 'primary' : ''"
                @click="chartView = 'both'"
                title="K线+成交量"
              >K+量</el-button>
              <el-button
                :type="chartView === 'kline' ? 'primary' : ''"
                @click="chartView = 'kline'"
                title="纯K线"
              >K线</el-button>
              <el-button
                :type="chartView === 'volume' ? 'primary' : ''"
                @click="chartView = 'volume'"
                title="纯成交量"
              >成交量</el-button>
            </el-button-group>

            <span v-if="klineLoading" style="color:#909399;font-size:12px;margin-left:12px">
              <el-icon class="is-loading"><Loading /></el-icon> 加载中...
            </span>
            <span v-if="!klineLoading && klineData.length > 0" style="color:#606266;font-size:12px;margin-left:12px">
              共 {{ klineData.length }} 根 · 滚轮缩放
            </span>
            <el-tag
              v-if="klineData.length > 0 && klineData[klineData.length-1]?.is_today"
              type="warning" size="small" effect="dark" style="margin-left:8px"
            >● 今日实时</el-tag>
          </div>

          <!-- 图注说明 -->
          <div class="chart-legend" v-if="!klineLoading && klineData.length > 0">
            <template v-if="chartView !== 'volume'">
              <span class="legend-item">
                <span class="legend-dot" style="background:#f56c6c"></span> 阳线（涨）
              </span>
              <span class="legend-item">
                <span class="legend-dot" style="background:#67c23a"></span> 阴线（跌）
              </span>
              <span class="legend-item">
                <span class="legend-line" style="background:#e6a23c"></span> MA5
              </span>
              <span class="legend-item">
                <span class="legend-line" style="background:#909399"></span> MA20
              </span>
            </template>
            <template v-if="chartView !== 'kline'">
              <span class="legend-item">
                <span class="legend-dot" style="background:#f56c6c"></span> 成交额（涨日，红）
              </span>
              <span class="legend-item">
                <span class="legend-dot" style="background:#67c23a"></span> 成交额（跌日，绿）
              </span>
            </template>
            <span class="legend-item" v-if="klineData[klineData.length-1]?.is_today">
              <span class="legend-dot" style="background:#409eff;border-radius:2px"></span> 今日实时
            </span>
          </div>

          <div v-if="klineLoading" class="kline-loading">
            <el-icon class="is-loading" style="font-size:24px"><Loading /></el-icon>
            <div style="margin-top:8px;color:#606266">K线加载中...</div>
          </div>
          <div v-else-if="klineData.length === 0" class="kline-loading">
            <div style="color:#606266">暂无K线数据</div>
            <el-button size="small" style="margin-top:8px" @click="loadKline">重新加载</el-button>
          </div>
          <v-chart v-else :option="klineOption" :style="{ height: chartView === 'both' ? '440px' : '360px' }" autoresize />
        </div>

        <!-- 新闻 -->
        <div class="news-card" v-if="newsData.length > 0">
          <div class="card-title">近期新闻</div>
          <div v-for="n in newsData" :key="n.title" class="news-item">
            <a :href="n.url || '#'" target="_blank" class="news-title">{{ n.title }}</a>
            <span class="news-meta">{{ n.source }} · {{ n.time }}</span>
          </div>
        </div>
      </template>
    </div>

    <!-- 添加自选股弹窗 -->
    <el-dialog v-model="showAddDialog" title="添加自选股" width="400px">
      <el-autocomplete
        v-model="addKeyword"
        :fetch-suggestions="handleSearch"
        placeholder="输入股票代码或名称"
        @select="onAddSelect"
        style="width:100%"
        clearable
      >
        <template #default="{ item }">
          <span>{{ item.name }}</span>
          <span style="color:#909399;margin-left:8px;font-size:12px">{{ item.symbol }}</span>
        </template>
      </el-autocomplete>
      <template #footer>
        <el-button @click="showAddDialog = false">取消</el-button>
      </template>
    </el-dialog>

    <!-- 设置提醒弹窗 -->
    <el-dialog v-model="showAlertDialog" title="设置价格提醒" width="400px">
      <el-form :model="alertForm" label-width="80px">
        <el-form-item label="提醒类型">
          <el-radio-group v-model="alertForm.alert_type">
            <el-radio value="price_above">价格突破</el-radio>
            <el-radio value="price_below">价格跌破</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="目标价格">
          <el-input-number v-model="alertForm.target_price" :precision="2" :step="0.1" style="width:100%" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="alertForm.message" placeholder="可选备注" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAlertDialog = false">取消</el-button>
        <el-button type="primary" @click="createAlert">创建提醒</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
defineOptions({ name: 'Market' })
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Plus, Delete, Loading } from '@element-plus/icons-vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CandlestickChart, LineChart, BarChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, LegendComponent,
  DataZoomComponent, MarkLineComponent
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { api } from '../api.js'
import { quotesMap } from '../store.js'

use([
  CandlestickChart, LineChart, BarChart,
  GridComponent, TooltipComponent, LegendComponent,
  DataZoomComponent, MarkLineComponent,
  CanvasRenderer
])

const router = useRouter()

const watchlist = ref([])
const currentSymbol = ref('')
const currentName = ref('')
const quote = ref(null)
const klineData = ref([])
const klineLoading = ref(false)
const newsData = ref([])
const klinePeriod = ref('daily')
const chartView = ref('both')  // 'both' | 'kline' | 'volume'
const searchKeyword = ref('')
const showAddDialog = ref(false)
const showAlertDialog = ref(false)
const addKeyword = ref('')
const alertForm = ref({ alert_type: 'price_above', target_price: 0, message: '' })

function pctClass(pct) {
  if (pct == null) return 'flat'
  return pct > 0 ? 'up' : pct < 0 ? 'down' : 'flat'
}

function formatPct(pct) {
  if (pct == null) return '--'
  return (pct > 0 ? '+' : '') + pct.toFixed(2) + '%'
}

async function loadWatchlist() {
  try {
    watchlist.value = await api.watchlistWithQuotes()
  } catch (e) {
    console.error('loadWatchlist:', e)
  }
}

async function selectSymbol(symbol, name) {
  currentSymbol.value = symbol
  currentName.value = name || symbol
  quote.value = null
  klineData.value = []
  newsData.value = []
  // 并行加载，K线单独处理 loading 状态
  loadQuote()
  loadKline()
  loadNews()
}

async function loadQuote() {
  // 先从 WebSocket 缓存里取（毫秒级）
  if (quotesMap[currentSymbol.value]) {
    quote.value = { ...quotesMap[currentSymbol.value] }
  }
  // 再从接口刷新（确保数据最新）
  try {
    const q = await api.quote(currentSymbol.value)
    if (q && !q.error) {
      quote.value = q
    }
  } catch (e) {
    console.error('loadQuote:', e)
  }
}

async function loadKline() {
  if (!currentSymbol.value) return
  klineLoading.value = true
  klineData.value = []
  try {
    const data = await api.kline(currentSymbol.value, klinePeriod.value, 120)
    console.log('kline data:', data?.length, 'bars for', currentSymbol.value)
    klineData.value = data || []
  } catch (e) {
    console.error('loadKline failed:', e)
    klineData.value = []
  } finally {
    klineLoading.value = false
  }
}

async function loadNews() {
  try {
    newsData.value = await api.news(currentSymbol.value, 8)
  } catch (e) {}
}

// 实时更新 quote + 今日K线最后一根
watch(quotesMap, (map) => {
  if (!currentSymbol.value) return
  const live = map[currentSymbol.value]
  if (!live) return

  // 更新行情头部
  if (quote.value) {
    quote.value.price = live.price
    quote.value.change = live.change
    quote.value.change_pct = live.change_pct
    quote.value.high = Math.max(quote.value.high || 0, live.price)
    quote.value.low = quote.value.low > 0 ? Math.min(quote.value.low, live.price) : live.price
    quote.value.volume = live.volume
    quote.value.turnover = live.turnover
  }

  // 更新自选股列表
  const item = watchlist.value.find(w => w.symbol === currentSymbol.value)
  if (item) {
    item.price = live.price
    item.change_pct = live.change_pct
  }

  // 实时更新今日K线（最后一根）
  if (klinePeriod.value === 'daily' && klineData.value.length > 0) {
    const today = new Date().toISOString().slice(0, 10)
    const last = klineData.value[klineData.value.length - 1]
    if (last.is_today || last.date === today) {
      // 更新最后一根K线的收盘价、最高、最低
      last.close = live.price
      last.high = Math.max(last.high, live.price)
      last.low = last.low > 0 ? Math.min(last.low, live.price) : live.price
      last.change_pct = live.change_pct
      last.volume = live.volume
      last.amount = live.turnover
      last.is_today = true
      // 触发响应式更新
      klineData.value = [...klineData.value]
    }
  }
}, { deep: true })

async function handleSearch(query, cb) {
  if (!query || query.length < 1) return cb([])
  try {
    const results = await api.search(query)
    cb(results.map(r => ({ ...r, value: r.name })))
  } catch (e) { cb([]) }
}

function onSearchSelect(item) {
  selectSymbol(item.symbol, item.name)
  searchKeyword.value = ''
}

function onAddSelect(item) {
  // 选中后直接添加
  api.watchlistAdd(item.symbol, item.name).then(() => {
    ElMessage.success(`已添加 ${item.name}`)
    showAddDialog.value = false
    addKeyword.value = ''
    loadWatchlist()
  }).catch(e => ElMessage.error(e.message))
}

async function addToWatchlist() {
  if (!currentSymbol.value) return
  try {
    await api.watchlistAdd(currentSymbol.value, currentName.value)
    ElMessage.success('已加入自选股')
    await loadWatchlist()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function removeFromWatchlist(symbol) {
  try {
    await api.watchlistRemove(symbol)
    watchlist.value = watchlist.value.filter(w => w.symbol !== symbol)
    if (currentSymbol.value === symbol) {
      currentSymbol.value = ''
      quote.value = null
      klineData.value = []
    }
  } catch (e) {
    ElMessage.error(e.message)
  }
}

function goAnalyze() {
  router.push({ path: '/agent', query: { symbol: currentSymbol.value, name: currentName.value, t: Date.now() } })
}

async function createAlert() {
  if (!currentSymbol.value) return
  try {
    await api.createAlert({
      symbol: currentSymbol.value,
      name: currentName.value,
      ...alertForm.value,
    })
    ElMessage.success('提醒已创建')
    showAlertDialog.value = false
  } catch (e) {
    ElMessage.error(e.message)
  }
}

// K线图配置
const klineOption = computed(() => {
  if (!klineData.value || klineData.value.length === 0) return {}

  const dates = klineData.value.map(b => b.date)
  const ohlc = klineData.value.map(b => [
    Number(b.open),
    Number(b.close),
    Number(b.low),   // ECharts candlestick: [open, close, low, high]
    Number(b.high),
  ])
  // 用 amount（成交额，元）作为成交量柱，历史和今日单位一致
  const volumes = klineData.value.map(b => Number(b.amount || b.volume))
  const closes = klineData.value.map(b => Number(b.close))

  const ma = (n) => closes.map((_, i) => {
    if (i < n - 1) return null
    const slice = closes.slice(i - n + 1, i + 1)
    return +(slice.reduce((a, b) => a + b, 0) / n).toFixed(2)
  })

  // 默认显示最近 60 根
  const zoomStart = Math.max(0, Math.round((1 - 60 / Math.max(dates.length, 1)) * 100))

  const commonTooltip = {
    trigger: 'axis',
    axisPointer: { type: 'cross' },
    backgroundColor: '#1e1e3a',
    borderColor: '#3a3a6a',
    textStyle: { color: '#e0e0e0', fontSize: 12 },
    formatter(params) {
      const p = params.find(p => p.seriesName === 'K线')
      const vol = params.find(p => p.seriesName === '成交量')
      const amtFmt = (v) => v >= 1e8 ? (v/1e8).toFixed(2)+'亿' : v >= 1e4 ? (v/1e4).toFixed(0)+'万' : v

      if (chartView.value === 'volume') {
        if (!vol) return ''
        return `<div style="padding:4px 8px">
          <div style="color:#909399;margin-bottom:4px">${params[0]?.name}</div>
          <div>成交额 <b style="color:#e0e0e0">${amtFmt(vol.value)}</b></div>
        </div>`
      }

      if (!p) return ''
      const [o, c, l, h] = p.value
      const cc = c >= o ? '#f56c6c' : '#67c23a'
      return `<div style="padding:4px 8px;min-width:130px">
        <div style="color:#909399;margin-bottom:4px;font-size:11px">${p.name}</div>
        <div style="display:flex;justify-content:space-between;gap:12px"><span style="color:#909399">开</span><b>${o}</b></div>
        <div style="display:flex;justify-content:space-between;gap:12px"><span style="color:#909399">收</span><b style="color:${cc}">${c}</b></div>
        <div style="display:flex;justify-content:space-between;gap:12px"><span style="color:#909399">高</span><b style="color:#f56c6c">${h}</b></div>
        <div style="display:flex;justify-content:space-between;gap:12px"><span style="color:#909399">低</span><b style="color:#67c23a">${l}</b></div>
        ${vol ? `<div style="display:flex;justify-content:space-between;gap:12px;margin-top:3px;border-top:1px solid #2a2a4a;padding-top:3px"><span style="color:#909399">成交额</span><b>${amtFmt(vol.value)}</b></div>` : ''}
      </div>`
    }
  }

  const commonDataZoom = [
    { type: 'inside', xAxisIndex: [0, 1], start: zoomStart, end: 100 },
    {
      type: 'slider', xAxisIndex: [0, 1], bottom: 6, height: 20,
      borderColor: '#2a2a4a', textStyle: { color: '#606266', fontSize: 10 },
      fillerColor: 'rgba(64,158,255,0.12)',
      handleStyle: { color: '#409eff' },
      start: zoomStart, end: 100,
    },
  ]

  const candleSeries = {
    name: 'K线', type: 'candlestick',
    xAxisIndex: 0, yAxisIndex: 0, data: ohlc,
    itemStyle: {
      color: '#f56c6c', color0: '#67c23a',
      borderColor: '#f56c6c', borderColor0: '#67c23a',
    },
    markLine: klineData.value[klineData.value.length - 1]?.is_today ? {
      silent: true, symbol: 'none',
      lineStyle: { color: '#409eff', type: 'dashed', width: 1, opacity: 0.5 },
      data: [{ type: 'max' }], label: { show: false },
    } : undefined,
  }

  const ma5Series = {
    name: 'MA5', type: 'line', xAxisIndex: 0, yAxisIndex: 0,
    data: ma(5), smooth: true, showSymbol: false,
    lineStyle: { width: 1.5, color: '#e6a23c' },
  }

  const ma20Series = {
    name: 'MA20', type: 'line', xAxisIndex: 0, yAxisIndex: 0,
    data: ma(20), smooth: true, showSymbol: false,
    lineStyle: { width: 1.5, color: '#909399' },
  }

  const volSeries = {
    name: '成交量', type: 'bar',
    xAxisIndex: chartView.value === 'both' ? 1 : 0,
    yAxisIndex: chartView.value === 'both' ? 1 : 0,
    data: volumes, barMaxWidth: 8,
    itemStyle: {
      color: (params) => {
        const bar = klineData.value[params.dataIndex]
        return bar && Number(bar.close) >= Number(bar.open) ? '#f56c6c' : '#67c23a'
      },
    },
  }

  // ---- 视图：K线 + 成交量（上下分割）----
  if (chartView.value === 'both') {
    return {
      backgroundColor: '#1a1a2e',
      animation: false,
      tooltip: commonTooltip,
      grid: [
        { left: 60, right: 16, top: 16, height: '60%' },
        { left: 60, right: 16, bottom: 50, height: '20%' },
      ],
      xAxis: [
        { type: 'category', data: dates, gridIndex: 0, axisLabel: { color: '#606266', fontSize: 11 }, axisLine: { lineStyle: { color: '#2a2a4a' } }, splitLine: { show: false } },
        { type: 'category', data: dates, gridIndex: 1, axisLabel: { show: false }, axisLine: { lineStyle: { color: '#2a2a4a' } } },
      ],
      yAxis: [
        { scale: true, gridIndex: 0, splitLine: { lineStyle: { color: '#2a2a4a', type: 'dashed' } }, axisLabel: { color: '#606266', fontSize: 11 }, axisLine: { show: false } },
        {
          scale: true, gridIndex: 1, splitLine: { show: false }, axisLine: { show: false },
          axisLabel: { color: '#606266', fontSize: 10, formatter: v => v >= 1e8 ? (v/1e8).toFixed(1)+'亿' : v >= 1e4 ? (v/1e4).toFixed(0)+'万' : v },
        },
      ],
      dataZoom: commonDataZoom,
      series: [candleSeries, ma5Series, ma20Series, volSeries],
    }
  }

  // ---- 视图：纯K线（全高）----
  if (chartView.value === 'kline') {
    return {
      backgroundColor: '#1a1a2e',
      animation: false,
      tooltip: commonTooltip,
      grid: [{ left: 60, right: 16, top: 16, bottom: 50 }],
      xAxis: [{ type: 'category', data: dates, gridIndex: 0, axisLabel: { color: '#606266', fontSize: 11 }, axisLine: { lineStyle: { color: '#2a2a4a' } }, splitLine: { show: false } }],
      yAxis: [{ scale: true, gridIndex: 0, splitLine: { lineStyle: { color: '#2a2a4a', type: 'dashed' } }, axisLabel: { color: '#606266', fontSize: 11 }, axisLine: { show: false } }],
      dataZoom: [
        { type: 'inside', xAxisIndex: [0], start: zoomStart, end: 100 },
        { type: 'slider', xAxisIndex: [0], bottom: 6, height: 20, borderColor: '#2a2a4a', textStyle: { color: '#606266', fontSize: 10 }, fillerColor: 'rgba(64,158,255,0.12)', handleStyle: { color: '#409eff' }, start: zoomStart, end: 100 },
      ],
      series: [
        { ...candleSeries, xAxisIndex: 0, yAxisIndex: 0 },
        { ...ma5Series, xAxisIndex: 0, yAxisIndex: 0 },
        { ...ma20Series, xAxisIndex: 0, yAxisIndex: 0 },
      ],
    }
  }

  // ---- 视图：纯成交量（全高）----
  return {
    backgroundColor: '#1a1a2e',
    animation: false,
    tooltip: commonTooltip,
    grid: [{ left: 60, right: 16, top: 16, bottom: 50 }],
    xAxis: [{ type: 'category', data: dates, gridIndex: 0, axisLabel: { color: '#606266', fontSize: 11 }, axisLine: { lineStyle: { color: '#2a2a4a' } }, splitLine: { show: false } }],
    yAxis: [{
      scale: true, gridIndex: 0, splitLine: { lineStyle: { color: '#2a2a4a', type: 'dashed' } }, axisLine: { show: false },
      axisLabel: { color: '#606266', fontSize: 10, formatter: v => v >= 1e8 ? (v/1e8).toFixed(1)+'亿' : v >= 1e4 ? (v/1e4).toFixed(0)+'万' : v },
    }],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0], start: zoomStart, end: 100 },
      { type: 'slider', xAxisIndex: [0], bottom: 6, height: 20, borderColor: '#2a2a4a', textStyle: { color: '#606266', fontSize: 10 }, fillerColor: 'rgba(64,158,255,0.12)', handleStyle: { color: '#409eff' }, start: zoomStart, end: 100 },
    ],
    series: [{ ...volSeries, xAxisIndex: 0, yAxisIndex: 0 }],
  }
})
onMounted(async () => {
  await loadWatchlist()
  // 支持从其他页面跳转过来时自动选中股票
  const { symbol, name } = router.currentRoute.value.query
  if (symbol) {
    selectSymbol(symbol, name || symbol)
  } else if (watchlist.value.length > 0) {
    selectSymbol(watchlist.value[0].symbol, watchlist.value[0].name)
  }
})
</script>

<style scoped>
.market-page {
  display: flex;
  gap: 16px;
  height: calc(100vh - 96px);
  overflow: hidden;
}

/* 左侧自选股 */
.sidebar {
  width: 200px;
  flex-shrink: 0;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  padding: 12px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.sidebar-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  font-weight: 600;
  color: #606266;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.watchlist-item {
  display: flex;
  align-items: center;
  padding: 7px 6px;
  border-radius: 6px;
  cursor: pointer;
  position: relative;
  transition: background 0.15s;
  gap: 4px;
}
.watchlist-item:hover { background: #22224a; }
.watchlist-item.active { background: #1e3a5f; border-left: 2px solid #409eff; }
.watchlist-item:hover .wl-del { opacity: 1; }

.wl-left { flex: 1; min-width: 0; }
.wl-name { font-size: 13px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.wl-symbol { font-size: 10px; color: #606266; margin-top: 1px; }
.wl-right { text-align: right; flex-shrink: 0; }
.wl-price { font-size: 13px; font-weight: 600; }
.wl-pct { font-size: 10px; }
.wl-del {
  opacity: 0;
  position: absolute;
  right: -2px;
  top: 50%;
  transform: translateY(-50%);
  transition: opacity 0.15s;
  width: 20px !important;
  height: 20px !important;
}

.empty-tip { text-align: center; color: #606266; font-size: 12px; padding: 20px 0; }

/* 右侧主区域 */
.main-panel {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

.search-bar { flex-shrink: 0; }

.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #606266;
  font-size: 14px;
  gap: 12px;
}
.empty-icon { font-size: 48px; }

/* 行情头部 */
.quote-header {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  padding: 16px 20px;
  flex-shrink: 0;
}

.qh-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 12px;
}

.quote-name {
  font-size: 18px;
  font-weight: 700;
  margin-bottom: 4px;
}
.quote-symbol { font-size: 12px; color: #909399; margin-left: 8px; font-weight: 400; }

.quote-price {
  font-size: 36px;
  font-weight: 700;
  line-height: 1.1;
}

.quote-change { font-size: 15px; margin-top: 2px; }

.quote-actions { display: flex; gap: 8px; flex-shrink: 0; }

.quote-meta {
  display: flex;
  gap: 20px;
  font-size: 12px;
  color: #606266;
  flex-wrap: wrap;
}
.quote-meta b { color: #c0c4cc; }

/* K线 */
.kline-card {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  padding: 12px 16px;
  flex-shrink: 0;
}

.kline-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.chart-legend {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 6px 4px;
  margin-bottom: 4px;
  flex-wrap: wrap;
  border-bottom: 1px solid #2a2a4a;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: #909399;
  white-space: nowrap;
}

.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  flex-shrink: 0;
}

.legend-line {
  width: 20px;
  height: 2px;
  border-radius: 1px;
  flex-shrink: 0;
}

.kline-loading {
  height: 200px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #606266;
}

/* 新闻 */
.news-card {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  padding: 16px;
  flex-shrink: 0;
}

.card-title {
  font-size: 12px;
  font-weight: 600;
  color: #606266;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 12px;
}

.news-item {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid #2a2a4a;
}
.news-item:last-child { border-bottom: none; }
.news-title {
  color: #c0c4cc;
  text-decoration: none;
  font-size: 13px;
  flex: 1;
  line-height: 1.4;
}
.news-title:hover { color: #409eff; }
.news-meta { font-size: 11px; color: #606266; white-space: nowrap; flex-shrink: 0; }

.loading-tip {
  color: #606266;
  font-size: 13px;
  padding: 20px;
  text-align: center;
}
</style>
