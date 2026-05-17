<template>
  <div class="overview-page">
    <!-- 顶部标题栏 -->
    <div class="page-header">
      <h2>市场总览</h2>
      <div class="header-right">
        <el-tag v-if="cacheStatus" :type="cacheStatus.ready ? 'success' : 'warning'" size="small" effect="dark">
          {{ cacheStatus.ready ? `全市场 ${cacheStatus.total} 只` : `缓存加载中 ${cacheStatus.total}/5000+` }}
        </el-tag>
        <span class="update-time" v-if="updateTime">更新于 {{ updateTime }}</span>
        <el-button size="small" :icon="Refresh" :loading="loading" @click="loadAll">刷新</el-button>
      </div>
    </div>

    <!-- 搜索框 -->
    <div class="search-bar">
      <el-input
        v-model="searchKeyword"
        placeholder="搜索股票代码或名称..."
        :prefix-icon="Search"
        clearable
        size="default"
        style="max-width: 400px"
        @clear="searchKeyword = ''"
      />
      <span v-if="searchKeyword" class="search-hint">找到 {{ searchResults.length }} 只</span>
    </div>

    <!-- 搜索结果 -->
    <div v-if="searchKeyword && searchResults.length > 0" class="filter-result">
      <div class="filter-header">
        <span>搜索结果 — {{ searchResults.length }} 只</span>
        <el-button size="small" @click="searchKeyword = ''" plain>清除</el-button>
      </div>
      <div class="stock-grid">
        <div
          v-for="item in searchResults.slice(0, 200)"
          :key="item.symbol"
          class="stock-chip"
          :class="item.change_pct > 0 ? 'chip-up' : item.change_pct < 0 ? 'chip-down' : 'chip-flat'"
          @click="openDetail(item)"
        >
          <div class="chip-name">{{ item.name }}</div>
          <div class="chip-code">{{ item.symbol }}</div>
          <div class="chip-price">{{ item.price?.toFixed(2) ?? '--' }}</div>
          <div class="chip-pct">{{ item.change_pct > 0 ? '+' : '' }}{{ item.change_pct?.toFixed(2) ?? '0.00' }}%</div>
        </div>
      </div>
    </div>
    <div v-else-if="searchKeyword && searchResults.length === 0" class="filter-result">
      <div class="empty-tip">未找到匹配的股票</div>
    </div>

    <!-- 市场情绪 -->
    <div class="sentiment-row" v-if="stats.total > 0 && !searchKeyword">
      <div class="sentiment-card" @click="filterBoard('up')" :class="{ active: boardFilter === 'up' }">
        <div class="sc-label">上涨</div>
        <div class="sc-value up">{{ stats.up }}</div>
      </div>
      <div class="sentiment-card" @click="filterBoard('down')" :class="{ active: boardFilter === 'down' }">
        <div class="sc-label">下跌</div>
        <div class="sc-value down">{{ stats.down }}</div>
      </div>
      <div class="sentiment-card" @click="filterBoard('flat')" :class="{ active: boardFilter === 'flat' }">
        <div class="sc-label">平盘</div>
        <div class="sc-value flat">{{ stats.flat }}</div>
      </div>
      <div class="sentiment-card" @click="filterBoard('limitUp')" :class="{ active: boardFilter === 'limitUp' }">
        <div class="sc-label">涨停</div>
        <div class="sc-value up">{{ stats.limitUp }}</div>
      </div>
      <div class="sentiment-card" @click="filterBoard('limitDown')" :class="{ active: boardFilter === 'limitDown' }">
        <div class="sc-label">跌停</div>
        <div class="sc-value down">{{ stats.limitDown }}</div>
      </div>
      <div class="sentiment-card wide">
        <div class="sc-label">市场情绪 — 点击卡片筛选</div>
        <el-progress
          :percentage="Math.round(stats.up / stats.total * 100)"
          :color="sentimentColor"
          :stroke-width="10"
          :show-text="false"
          style="margin-top:6px"
        />
        <div style="font-size:11px;color:#909399;margin-top:4px">
          涨 {{ Math.round(stats.up / stats.total * 100) }}% · 跌 {{ Math.round(stats.down / stats.total * 100) }}%
        </div>
      </div>
    </div>

    <!-- 筛选结果 -->
    <div v-if="boardFilter && !searchKeyword" class="filter-result">
      <div class="filter-header">
        <span>{{ filterLabel }} — {{ filteredStocks.length }} 只</span>
        <el-button size="small" @click="boardFilter = ''" plain>清除筛选</el-button>
      </div>
      <div class="stock-grid">
        <div
          v-for="item in filteredStocks.slice(0, 200)"
          :key="item.symbol"
          class="stock-chip"
          :class="item.change_pct > 0 ? 'chip-up' : item.change_pct < 0 ? 'chip-down' : 'chip-flat'"
          @click="openDetail(item)"
        >
          <div class="chip-name">{{ item.name }}</div>
          <div class="chip-code">{{ item.symbol }}</div>
          <div class="chip-price">{{ item.price?.toFixed(2) ?? '--' }}</div>
          <div class="chip-pct">{{ item.change_pct > 0 ? '+' : '' }}{{ item.change_pct?.toFixed(2) ?? '0.00' }}%</div>
        </div>
      </div>
    </div>

    <!-- 三栏榜单 -->
    <div class="boards-row" v-if="!boardFilter && !searchKeyword">
      <!-- 涨幅榜 -->
      <div class="board-card">
        <div class="board-title"><span class="up">▲</span> 涨幅榜</div>
        <div v-if="loading && gainers.length === 0" class="board-loading">
          <el-icon class="is-loading"><Loading /></el-icon> 加载中...
        </div>
        <div v-else class="board-list">
          <div v-for="(item, i) in gainers" :key="item.symbol" class="board-item" @click="openDetail(item)">
            <span class="rank" :class="i < 3 ? 'rank-top' : ''">{{ i + 1 }}</span>
            <div class="bi-info">
              <div class="bi-name">{{ item.name }}</div>
              <div class="bi-symbol">{{ item.symbol }}</div>
            </div>
            <div class="bi-right">
              <div class="bi-price">{{ item.price?.toFixed(2) }}</div>
              <div class="bi-pct up">+{{ item.change_pct?.toFixed(2) }}%</div>
            </div>
          </div>
        </div>
      </div>

      <!-- 跌幅榜 -->
      <div class="board-card">
        <div class="board-title"><span class="down">▼</span> 跌幅榜</div>
        <div v-if="loading && losers.length === 0" class="board-loading">
          <el-icon class="is-loading"><Loading /></el-icon> 加载中...
        </div>
        <div v-else class="board-list">
          <div v-for="(item, i) in losers" :key="item.symbol" class="board-item" @click="openDetail(item)">
            <span class="rank" :class="i < 3 ? 'rank-top' : ''">{{ i + 1 }}</span>
            <div class="bi-info">
              <div class="bi-name">{{ item.name }}</div>
              <div class="bi-symbol">{{ item.symbol }}</div>
            </div>
            <div class="bi-right">
              <div class="bi-price">{{ item.price?.toFixed(2) }}</div>
              <div class="bi-pct down">{{ item.change_pct?.toFixed(2) }}%</div>
            </div>
          </div>
        </div>
      </div>

      <!-- 成交额榜 -->
      <div class="board-card">
        <div class="board-title"><span style="color:#e6a23c">💰</span> 成交额榜</div>
        <div v-if="loading && mostActive.length === 0" class="board-loading">
          <el-icon class="is-loading"><Loading /></el-icon> 加载中...
        </div>
        <div v-else class="board-list">
          <div v-for="(item, i) in mostActive" :key="item.symbol" class="board-item" @click="openDetail(item)">
            <span class="rank" :class="i < 3 ? 'rank-top' : ''">{{ i + 1 }}</span>
            <div class="bi-info">
              <div class="bi-name">{{ item.name }}</div>
              <div class="bi-symbol">{{ item.symbol }}</div>
            </div>
            <div class="bi-right">
              <div class="bi-price">{{ item.price?.toFixed(2) }}</div>
              <div class="bi-pct" :class="item.change_pct >= 0 ? 'up' : 'down'">
                {{ item.change_pct >= 0 ? '+' : '' }}{{ item.change_pct?.toFixed(2) }}%
              </div>
              <div class="bi-vol">{{ fmtAmt(item.turnover) }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 自选股实时行情 -->
    <div class="realtime-card" v-if="!boardFilter && !searchKeyword">
      <div class="card-title">
        自选股实时行情
        <el-tag size="small" type="info" style="margin-left:8px">{{ watchlistQuotes.length }} 只</el-tag>
      </div>
      <el-table :data="watchlistQuotes" size="small" @row-click="(row) => openDetail(row)" style="cursor:pointer">
        <el-table-column label="股票" min-width="120">
          <template #default="{ row }">
            <div style="font-weight:600">{{ row.name }}</div>
            <div style="font-size:11px;color:#606266">{{ row.symbol }}</div>
          </template>
        </el-table-column>
        <el-table-column label="最新价" width="90" align="right">
          <template #default="{ row }">
            <span :class="row.change_pct >= 0 ? 'up' : 'down'" style="font-weight:600;font-size:15px">
              {{ row.price?.toFixed(2) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="涨跌幅" width="90" align="right">
          <template #default="{ row }">
            <el-tag :type="row.change_pct > 0 ? 'danger' : row.change_pct < 0 ? 'success' : 'info'" size="small" effect="dark">
              {{ row.change_pct >= 0 ? '+' : '' }}{{ row.change_pct?.toFixed(2) }}%
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="涨跌额" width="80" align="right">
          <template #default="{ row }">
            <span :class="row.change >= 0 ? 'up' : 'down'">{{ row.change >= 0 ? '+' : '' }}{{ row.change?.toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="今开" width="80" align="right">
          <template #default="{ row }">{{ row.open?.toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="最高" width="80" align="right">
          <template #default="{ row }"><span class="up">{{ row.high?.toFixed(2) }}</span></template>
        </el-table-column>
        <el-table-column label="最低" width="80" align="right">
          <template #default="{ row }"><span class="down">{{ row.low?.toFixed(2) }}</span></template>
        </el-table-column>
        <el-table-column label="成交额" width="100" align="right">
          <template #default="{ row }">{{ fmtAmt(row.turnover) }}</template>
        </el-table-column>
      </el-table>
      <div v-if="watchlistQuotes.length === 0" class="empty-tip">
        暂无自选股，请在「行情」页添加
      </div>
    </div>

    <!-- ===== 股票详情抽屉 ===== -->
    <el-drawer
      v-model="drawerVisible"
      :title="drawerStock?.name + '（' + drawerStock?.symbol + '）'"
      direction="rtl"
      size="520px"
      :destroy-on-close="true"
    >
      <div v-if="drawerStock" class="drawer-content">
        <!-- 实时行情 -->
        <div class="drawer-quote">
          <div class="dq-price" :class="drawerStock.change_pct >= 0 ? 'up' : 'down'">
            {{ drawerStock.price?.toFixed(2) }}
          </div>
          <div class="dq-change" :class="drawerStock.change_pct >= 0 ? 'up' : 'down'">
            {{ drawerStock.change >= 0 ? '+' : '' }}{{ drawerStock.change?.toFixed(2) }}
            （{{ drawerStock.change_pct >= 0 ? '+' : '' }}{{ drawerStock.change_pct?.toFixed(2) }}%）
          </div>
          <div class="dq-meta">
            <span>今开 <b>{{ drawerStock.open?.toFixed(2) }}</b></span>
            <span>最高 <b class="up">{{ drawerStock.high?.toFixed(2) }}</b></span>
            <span>最低 <b class="down">{{ drawerStock.low?.toFixed(2) }}</b></span>
            <span>昨收 <b>{{ drawerStock.prev_close?.toFixed(2) }}</b></span>
            <span>成交额 <b>{{ fmtAmt(drawerStock.turnover) }}</b></span>
          </div>
          <div class="dq-actions">
            <el-button type="success" size="small" @click="addToWatchlist(drawerStock)">+ 自选</el-button>
            <el-button type="primary" size="small" @click="goAnalyze(drawerStock)">Agent分析</el-button>
            <el-button size="small" @click="goKline(drawerStock)">查看K线</el-button>
            <el-button size="small" @click="showAlertFor(drawerStock)">🔔 设提醒</el-button>
          </div>
        </div>

        <!-- K线图（迷你版） -->
        <div class="drawer-kline">
          <div class="drawer-section-title">日K线（近60日）</div>
          <div v-if="drawerKlineLoading" class="drawer-loading">
            <el-icon class="is-loading"><Loading /></el-icon> 加载K线...
          </div>
          <div v-else-if="drawerKline.length > 0 && drawerKline.length < 5" class="drawer-loading" style="color:#e6a23c">
            新股上市，K线数据较少
          </div>
          <v-chart v-else-if="drawerKline.length >= 5" :option="drawerKlineOption" style="height:220px" autoresize />
          <div v-else class="drawer-loading" style="color:#606266">暂无K线数据</div>
        </div>

        <!-- 近期新闻 -->
        <div class="drawer-news">
          <div class="drawer-section-title">近期新闻</div>
          <div v-if="drawerNewsLoading" class="drawer-loading">
            <el-icon class="is-loading"><Loading /></el-icon> 加载新闻...
          </div>
          <div v-else-if="drawerNews.length === 0" class="drawer-loading" style="color:#606266">暂无新闻</div>
          <div v-for="n in drawerNews" :key="n.title" class="drawer-news-item">
            <a :href="n.url || '#'" target="_blank" class="news-link">{{ n.title }}</a>
            <div class="news-meta">{{ n.source }} · {{ n.time?.slice(0, 16) }}</div>
          </div>
        </div>
      </div>
    </el-drawer>

    <!-- 设置提醒弹窗 -->
    <el-dialog v-model="alertDialogVisible" title="设置价格提醒" width="400px">
      <el-form :model="alertForm" label-width="80px">
        <el-form-item label="股票">{{ alertForm.name }}（{{ alertForm.symbol }}）</el-form-item>
        <el-form-item label="提醒类型">
          <el-radio-group v-model="alertForm.alert_type">
            <el-radio value="price_above">价格突破</el-radio>
            <el-radio value="price_below">价格跌破</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="目标价格">
          <el-input-number v-model="alertForm.target_price" :precision="2" :step="0.1" style="width:100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="alertDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="createAlert">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
defineOptions({ name: 'Overview' })
import { ref, computed, onMounted, onUnmounted, onActivated, onDeactivated, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh, Loading, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CandlestickChart, LineChart, BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { api } from '../api.js'
import { quotesMap } from '../store.js'

use([CandlestickChart, LineChart, BarChart, GridComponent, TooltipComponent, DataZoomComponent, CanvasRenderer])

const router = useRouter()
const loading = ref(false)
const updateTime = ref('')
const allQuotes = ref([])
const watchlistQuotes = ref([])
const cacheStatus = ref(null)
const boardFilter = ref('')

// 搜索
const searchKeyword = ref('')
const searchResults = computed(() => {
  const kw = searchKeyword.value.trim().toLowerCase()
  if (!kw) return []
  return allQuotes.value.filter(q =>
    q.symbol?.toLowerCase().includes(kw) || q.name?.toLowerCase().includes(kw)
  )
})

// 抽屉状态
const drawerVisible = ref(false)
const drawerStock = ref(null)
const drawerKline = ref([])
const drawerKlineLoading = ref(false)
const drawerNews = ref([])
const drawerNewsLoading = ref(false)

// 提醒弹窗
const alertDialogVisible = ref(false)
const alertForm = ref({ symbol: '', name: '', alert_type: 'price_above', target_price: 0 })

// 榜单
const gainers = computed(() =>
  [...allQuotes.value].filter(q => q.change_pct > 0).sort((a, b) => b.change_pct - a.change_pct).slice(0, 20)
)
const losers = computed(() =>
  [...allQuotes.value].filter(q => q.change_pct < 0).sort((a, b) => a.change_pct - b.change_pct).slice(0, 20)
)
const mostActive = computed(() =>
  [...allQuotes.value].filter(q => q.turnover > 0).sort((a, b) => b.turnover - a.turnover).slice(0, 20)
)
// 统计
const stats = computed(() => {
  const total = allQuotes.value.length
  const up = allQuotes.value.filter(q => q.change_pct > 0).length
  const down = allQuotes.value.filter(q => q.change_pct < 0).length
  const flat = total - up - down
  const limitUp = allQuotes.value.filter(q => q.change_pct >= 9.9).length
  const limitDown = allQuotes.value.filter(q => q.change_pct <= -9.9).length
  return { total, up, down, flat, limitUp, limitDown }
})

const sentimentColor = computed(() => {
  const pct = stats.value.total > 0 ? stats.value.up / stats.value.total : 0.5
  if (pct > 0.6) return '#f56c6c'
  if (pct < 0.4) return '#67c23a'
  return '#e6a23c'
})

// 筛选
const filterLabel = computed(() => ({
  up: '上涨股票', down: '下跌股票', flat: '平盘股票',
  limitUp: '涨停股票', limitDown: '跌停股票',
}[boardFilter.value] || ''))

const filteredStocks = computed(() => {
  const f = boardFilter.value
  if (f === 'up') return allQuotes.value.filter(q => q.change_pct > 0).sort((a, b) => b.change_pct - a.change_pct)
  if (f === 'down') return allQuotes.value.filter(q => q.change_pct < 0).sort((a, b) => a.change_pct - b.change_pct)
  if (f === 'flat') return allQuotes.value.filter(q => q.change_pct === 0)
  if (f === 'limitUp') return allQuotes.value.filter(q => q.change_pct >= 9.9)
  if (f === 'limitDown') return allQuotes.value.filter(q => q.change_pct <= -9.9)
  return []
})

function filterBoard(type) {
  boardFilter.value = boardFilter.value === type ? '' : type
}

// 实时更新自选股 & 抽屉价格
watch(quotesMap, (map) => {
  for (const row of watchlistQuotes.value) {
    const q = map[row.symbol]
    if (q) { row.price = q.price; row.change = q.change; row.change_pct = q.change_pct }
  }
  if (drawerStock.value && map[drawerStock.value.symbol]) {
    const q = map[drawerStock.value.symbol]
    drawerStock.value = { ...drawerStock.value, price: q.price, change: q.change, change_pct: q.change_pct }
  }
}, { deep: true })

async function loadAll() {
  loading.value = true
  try {
    const [hot, wl] = await Promise.all([api.hot(5000), api.watchlistWithQuotes()])
    allQuotes.value = hot
    watchlistQuotes.value = wl
    updateTime.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    cacheStatus.value = { ready: hot.length >= 1000, total: hot.length }
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

// 打开详情抽屉
async function openDetail(item) {
  drawerStock.value = { ...item }
  drawerVisible.value = true
  drawerKline.value = []
  drawerNews.value = []

  drawerKlineLoading.value = true
  drawerNewsLoading.value = true

  api.kline(item.symbol, 'daily', 60)
    .then(data => { drawerKline.value = data || [] })
    .catch(() => {})
    .finally(() => { drawerKlineLoading.value = false })

  api.news(item.symbol, 6)
    .then(data => { drawerNews.value = data || [] })
    .catch(() => {})
    .finally(() => { drawerNewsLoading.value = false })

  // 获取完整行情（含开高低）
  api.quote(item.symbol)
    .then(q => { if (q && !q.error) drawerStock.value = { ...drawerStock.value, ...q } })
    .catch(() => {})
}

// 抽屉K线图配置
const drawerKlineOption = computed(() => {
  if (!drawerKline.value.length) return {}
  const dates = drawerKline.value.map(b => b.date)
  const ohlc = drawerKline.value.map(b => [Number(b.open), Number(b.close), Number(b.low), Number(b.high)])
  const closes = drawerKline.value.map(b => Number(b.close))
  const ma5 = closes.map((_, i) =>
    i < 4 ? null : +(closes.slice(i - 4, i + 1).reduce((a, b) => a + b, 0) / 5).toFixed(2)
  )
  const ma20 = closes.map((_, i) =>
    i < 19 ? null : +(closes.slice(i - 19, i + 1).reduce((a, b) => a + b, 0) / 20).toFixed(2)
  )

  return {
    backgroundColor: '#16162a',
    animation: false,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: '#1e1e3a',
      borderColor: '#3a3a6a',
      textStyle: { color: '#e0e0e0', fontSize: 11 },
      formatter(params) {
        const p = params.find(p => p.seriesName === 'K')
        if (!p) return ''
        const [o, c, l, h] = p.value
        const cc = c >= o ? '#f56c6c' : '#67c23a'
        return `<div style="padding:3px 6px;font-size:11px">
          <div style="color:#909399">${p.name}</div>
          <div>开<b style="margin-left:4px">${o}</b> 收<b style="margin-left:4px;color:${cc}">${c}</b></div>
          <div>高<b style="margin-left:4px;color:#f56c6c">${h}</b> 低<b style="margin-left:4px;color:#67c23a">${l}</b></div>
        </div>`
      },
    },
    grid: { left: 50, right: 8, top: 8, bottom: 30 },
    xAxis: {
      type: 'category', data: dates,
      axisLabel: { color: '#606266', fontSize: 10 },
      axisLine: { lineStyle: { color: '#2a2a4a' } },
      splitLine: { show: false },
    },
    yAxis: {
      scale: true,
      splitLine: { lineStyle: { color: '#2a2a4a', type: 'dashed' } },
      axisLabel: { color: '#606266', fontSize: 10 },
      axisLine: { show: false },
    },
    dataZoom: [{ type: 'inside', start: 0, end: 100 }],
    series: [
      {
        name: 'K', type: 'candlestick', data: ohlc,
        itemStyle: { color: '#f56c6c', color0: '#67c23a', borderColor: '#f56c6c', borderColor0: '#67c23a' },
      },
      { name: 'MA5', type: 'line', data: ma5, smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#e6a23c' } },
      { name: 'MA20', type: 'line', data: ma20, smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#909399' } },
    ],
  }
})

function goAnalyze(item) {
  router.push({ path: '/agent', query: { symbol: item.symbol, name: item.name } })
  drawerVisible.value = false
}

function goKline(item) {
  router.push({ path: '/market', query: { symbol: item.symbol, name: item.name } })
  drawerVisible.value = false
}

async function addToWatchlist(item) {
  try {
    await api.watchlistAdd(item.symbol, item.name)
    ElMessage.success(`已添加 ${item.name}`)
  } catch (e) {
    ElMessage.error(e.message)
  }
}

function showAlertFor(item) {
  alertForm.value = { symbol: item.symbol, name: item.name, alert_type: 'price_above', target_price: item.price || 0 }
  alertDialogVisible.value = true
}

async function createAlert() {
  try {
    await api.createAlert(alertForm.value)
    ElMessage.success('提醒已创建')
    alertDialogVisible.value = false
  } catch (e) {
    ElMessage.error(e.message)
  }
}

function fmtAmt(v) {
  if (!v) return '--'
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (v >= 1e4) return (v / 1e4).toFixed(0) + '万'
  return v.toFixed(0)
}

// 定时刷新（30秒）— keep-alive 友好：deactivate 暂停 / activate 恢复
let timer = null
function _startTimer() {
  if (timer) return
  timer = setInterval(loadAll, 30000)
}
function _stopTimer() {
  if (timer) { clearInterval(timer); timer = null }
}
onMounted(() => {
  loadAll()
  _startTimer()
})
onActivated(() => {
  loadAll()
  _startTimer()
})
onDeactivated(_stopTimer)
onUnmounted(_stopTimer)
</script>

<style scoped>
.overview-page { display: flex; flex-direction: column; gap: 16px; }

/* 标题栏 */
.page-header { display: flex; justify-content: space-between; align-items: center; }
.page-header h2 { font-size: 20px; font-weight: 700; }
.header-right { display: flex; align-items: center; gap: 10px; }
.update-time { font-size: 12px; color: #606266; }

/* 搜索栏 */
.search-bar { display: flex; align-items: center; gap: 10px; }
.search-hint { font-size: 12px; color: #606266; }

/* 情绪卡片 */
.sentiment-row { display: flex; gap: 10px; flex-wrap: wrap; }
.sentiment-card {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  padding: 10px 18px;
  min-width: 70px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.2s;
}
.sentiment-card:hover { border-color: #409eff; }
.sentiment-card.active { border-color: #409eff; background: #1e3a5f; }
.sentiment-card.wide { flex: 1; min-width: 200px; text-align: left; padding: 10px 14px; cursor: default; }
.sc-label { font-size: 11px; color: #606266; margin-bottom: 3px; }
.sc-value { font-size: 22px; font-weight: 700; }

/* 筛选 / 搜索结果 */
.filter-result { background: #1a1a2e; border: 1px solid #2a2a4a; border-radius: 8px; padding: 14px; }
.filter-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; font-size: 13px; font-weight: 600; color: #c0c4cc; }

/* 股票色块网格 */
.stock-grid { display: flex; flex-wrap: wrap; gap: 6px; }
.stock-chip {
  padding: 6px 10px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  transition: opacity 0.15s;
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 72px;
}
.stock-chip:hover { opacity: 0.8; }
.chip-up   { background: rgba(245, 108, 108, 0.18); border: 1px solid rgba(245, 108, 108, 0.35); }
.chip-down { background: rgba(103, 194,  58, 0.18); border: 1px solid rgba(103, 194,  58, 0.35); }
.chip-flat { background: rgba(144, 147, 153, 0.18); border: 1px solid rgba(144, 147, 153, 0.35); }
.chip-name  { font-weight: 600; color: #e0e0e0; white-space: nowrap; }
.chip-code  { font-size: 10px; color: #909399; margin-top: 1px; }
.chip-price { font-size: 11px; color: #c0c4cc; margin-top: 2px; }
.chip-pct   { font-size: 11px; font-weight: 700; margin-top: 1px; }
.chip-up   .chip-pct { color: #f56c6c; }
.chip-down .chip-pct { color: #67c23a; }
.chip-flat .chip-pct { color: #909399; }

/* 三栏榜单 */
.boards-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; align-items: start; }
.board-card { background: #1a1a2e; border: 1px solid #2a2a4a; border-radius: 8px; padding: 14px; }
.board-title { font-size: 13px; font-weight: 600; color: #c0c4cc; margin-bottom: 10px; display: flex; align-items: center; gap: 6px; }
.board-loading { height: 80px; display: flex; align-items: center; justify-content: center; color: #606266; gap: 6px; font-size: 13px; }
.board-list {
  display: flex;
  flex-direction: column;
  gap: 1px;
  max-height: 520px;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: #2a2a4a transparent;
}
.board-list::-webkit-scrollbar { width: 4px; }
.board-list::-webkit-scrollbar-track { background: transparent; }
.board-list::-webkit-scrollbar-thumb { background: #2a2a4a; border-radius: 2px; }
.board-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 4px;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.15s;
}
.board-item:hover { background: #22224a; }
.rank { width: 18px; height: 18px; border-radius: 3px; background: #2a2a4a; color: #606266; font-size: 11px; font-weight: 600; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.rank-top { background: #1e3a5f; color: #409eff; }
.bi-info { flex: 1; min-width: 0; }
.bi-name { font-size: 13px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bi-symbol { font-size: 10px; color: #606266; }
.bi-right { text-align: right; flex-shrink: 0; }
.bi-price { font-size: 13px; font-weight: 600; color: #e0e0e0; }
.bi-pct { font-size: 12px; font-weight: 600; }
.bi-vol { font-size: 10px; color: #606266; }

/* 自选股表格 */
.realtime-card { background: #1a1a2e; border: 1px solid #2a2a4a; border-radius: 8px; padding: 16px; }
.card-title { font-size: 13px; font-weight: 600; color: #909399; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 12px; display: flex; align-items: center; }
.empty-tip { text-align: center; color: #606266; padding: 30px; font-size: 13px; }

/* 通用颜色 */
.up   { color: #f56c6c; }
.down { color: #67c23a; }
.flat { color: #909399; }

/* 抽屉内容 */
.drawer-content { display: flex; flex-direction: column; gap: 16px; padding: 4px 0; }

.drawer-quote { background: #16162a; border-radius: 8px; padding: 16px; }
.dq-price { font-size: 36px; font-weight: 700; line-height: 1.1; }
.dq-change { font-size: 16px; margin: 4px 0 10px; }
.dq-meta { display: flex; gap: 14px; font-size: 12px; color: #606266; flex-wrap: wrap; margin-bottom: 12px; }
.dq-meta b { color: #c0c4cc; }
.dq-actions { display: flex; gap: 8px; flex-wrap: wrap; }

.drawer-kline { background: #16162a; border-radius: 8px; padding: 12px; }
.drawer-news  { background: #16162a; border-radius: 8px; padding: 12px; }
.drawer-section-title { font-size: 12px; font-weight: 600; color: #606266; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 10px; }
.drawer-loading { height: 60px; display: flex; align-items: center; justify-content: center; color: #606266; gap: 6px; font-size: 13px; }

.drawer-news-item { padding: 8px 0; border-bottom: 1px solid #2a2a4a; }
.drawer-news-item:last-child { border-bottom: none; }
.news-link { color: #c0c4cc; text-decoration: none; font-size: 13px; line-height: 1.4; display: block; }
.news-link:hover { color: #409eff; }
.news-meta { font-size: 11px; color: #606266; margin-top: 3px; }
</style>
