<template>
  <div class="advisor-page">
    <div class="advisor-hero">
      <div>
        <div class="hero-title">实时股票推荐</div>
        <div class="hero-subtitle">实时行情 + AI 终审 + 模型进化概率，输出可手动挂单参考价</div>
      </div>
      <div class="hero-actions">
        <el-tag :type="autoRefresh ? 'success' : 'info'" effect="dark">
          {{ autoRefresh ? '自动刷新中' : '手动模式' }}
        </el-tag>
        <el-button @click="toggleAuto" plain>{{ autoRefresh ? '暂停实时分析' : '开启实时分析' }}</el-button>
        <el-button type="primary" :loading="loading" @click="refreshNow(true)">立即重新分析</el-button>
      </div>
    </div>

    <div class="status-row">
      <span>刷新间隔：{{ refreshIntervalSec }} 秒</span>
      <span v-if="lastUpdated">最后分析：{{ lastUpdated }}</span>
      <span v-if="result?.cached">使用缓存结果</span>
      <span v-if="result?.elapsed_ms">耗时：{{ Math.round(result.elapsed_ms / 1000) }} 秒</span>
      <span v-if="result?.evolution?.model_version">模型：{{ result.evolution.model_version }}</span>
    </div>

    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      show-icon
      style="margin-bottom:14px"
    />

    <el-row :gutter="16">
      <el-col :span="14">
        <el-card shadow="never" class="main-card">
          <template #header>
            <div class="card-header">
              <span>当前最值得关注的买入机会</span>
              <el-tag v-if="bestPick" :type="ratingType(bestPick.trade_plan?.rating)" effect="dark">
                {{ bestPick.trade_plan?.rating || '观察' }}
              </el-tag>
            </div>
          </template>

          <el-skeleton v-if="loading && !bestPick" :rows="8" animated />
          <el-empty v-else-if="!bestPick" description="暂无可参考买入机会，点击立即重新分析" />

          <div v-else class="pick-main">
            <div class="pick-top">
              <div>
                <div class="stock-name">{{ bestPick.name }}</div>
                <div class="stock-code">{{ bestPick.symbol }}</div>
              </div>
              <div class="price-box">
                <div class="price-label">实时价</div>
                <div class="live-price" :class="bestPick.change_pct >= 0 ? 'up' : 'down'">
                  ¥{{ fmt(bestPick.price) }}
                </div>
                <div :class="bestPick.change_pct >= 0 ? 'up' : 'down'">
                  {{ bestPick.change_pct >= 0 ? '+' : '' }}{{ fmt(bestPick.change_pct) }}%
                </div>
              </div>
            </div>

            <div class="order-plan">
              <div class="plan-cell primary">
                <div class="plan-label">建议挂单价</div>
                <div class="plan-value">¥{{ fmt(entryPrice(bestPick)) }}</div>
                <div class="plan-sub">尽量接近预测低吸价，不建议无脑追高</div>
              </div>
              <div class="plan-cell">
                <div class="plan-label">可接受买入区间</div>
                <div class="plan-value small">¥{{ fmt(bestPick.trade_plan?.entry_low) }} - ¥{{ fmt(bestPick.trade_plan?.entry_high) }}</div>
              </div>
              <div class="plan-cell danger">
                <div class="plan-label">止损价</div>
                <div class="plan-value">¥{{ fmt(bestPick.trade_plan?.stop_loss) }}</div>
                <div class="plan-sub">跌破则撤退</div>
              </div>
              <div class="plan-cell target">
                <div class="plan-label">短线目标</div>
                <div class="plan-value">¥{{ fmt(bestPick.trade_plan?.target1) }}</div>
                <div class="plan-sub">预期 +{{ bestPick.trade_plan?.expected_return_pct ?? '--' }}%</div>
              </div>
              <div class="plan-cell evolve">
                <div class="plan-label">模型预测</div>
                <div class="plan-value">{{ bestPick.evolution?.probability_pct ?? '--' }}%</div>
                <div class="plan-sub">{{ bestPick.evolution?.best_horizon_days || '--' }} 日内达到 +{{ bestPick.evolution?.target_return_pct ?? '--' }}%</div>
              </div>
            </div>

            <div class="summary-line">
              {{ bestPick.trade_plan?.tomorrow_plan || '等待更明确的入场信号' }}
            </div>

            <div class="reasons-grid">
              <div class="reason-block">
                <div class="block-title">为什么可以买</div>
                <ul>
                  <li v-for="(r, i) in bestPick.trade_plan?.reasons || []" :key="i">{{ r }}</li>
                  <li v-if="!(bestPick.trade_plan?.reasons || []).length">综合指标暂未给出明确理由</li>
                </ul>
              </div>
              <div class="reason-block warning">
                <div class="block-title">必须注意的风险</div>
                <ul>
                  <li v-for="(w, i) in bestPick.trade_plan?.warnings || []" :key="i">{{ w }}</li>
                  <li v-if="!(bestPick.trade_plan?.warnings || []).length">暂无明显风险，但仍需按止损执行</li>
                </ul>
              </div>
            </div>

            <div class="signal-strip">
              <el-tag v-for="tag in (bestPick.tags || []).slice(0, 8)" :key="tag" size="small" effect="plain">{{ tag }}</el-tag>
            </div>
          </div>
        </el-card>
      </el-col>

      <el-col :span="10">
        <el-card shadow="never" class="side-card">
          <template #header>
            <div class="card-header">
              <span>候选列表</span>
              <span class="muted">按综合评分排序</span>
            </div>
          </template>

          <el-skeleton v-if="loading && !picks.length" :rows="7" animated />
          <el-empty v-else-if="!picks.length" description="暂无候选" />

          <div v-else class="candidate-list">
            <div
              v-for="(s, i) in picks.slice(0, 8)"
              :key="s.symbol"
              class="candidate-item"
              :class="{ active: bestPick?.symbol === s.symbol }"
              @click="selectedSymbol = s.symbol"
            >
              <div class="rank">{{ i + 1 }}</div>
              <div class="candidate-info">
                <div class="candidate-name">{{ s.name }}</div>
                <div class="candidate-code">{{ s.symbol }}</div>
              </div>
              <div class="candidate-right">
                <div :class="s.change_pct >= 0 ? 'up' : 'down'">¥{{ fmt(s.price) }}</div>
                <div class="muted">概率 {{ s.evolution?.probability_pct ?? '--' }}%</div>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api.js'

const loading = ref(false)
const error = ref('')
const result = ref(null)
const selectedSymbol = ref('')
const autoRefresh = ref(true)
const refreshIntervalSec = 300
const lastUpdated = ref('')
let timer = null

const picks = computed(() => result.value?.results || [])
const bestPick = computed(() => {
  if (!picks.value.length) return null
  return picks.value.find(s => s.symbol === selectedSymbol.value) || picks.value[0]
})

function fmt(v) {
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(2) : '--'
}

function entryPrice(stock) {
  const plan = stock?.trade_plan || {}
  if (plan.entry_low) return plan.entry_low
  if (plan.entry_mid) return plan.entry_mid
  return stock?.price ? stock.price * 0.985 : 0
}

function ratingType(rating) {
  if (rating === '强烈推荐') return 'danger'
  if (rating === '推荐') return 'warning'
  if (rating === '观察') return 'info'
  return 'info'
}

async function refreshNow(force = false) {
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    const data = await api.scannerScan({
      top_n: 10,
      min_score: 50,
      candidate_pool: 120,
      use_cache: !force,
      enable_fundamental: true,
      enable_llm: true,
      llm_top_n: 5,
    })
    result.value = data
    if (!selectedSymbol.value && data.results?.[0]) selectedSymbol.value = data.results[0].symbol
    lastUpdated.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    if (!data.results?.length) ElMessage.warning('当前没有足够可靠的买入机会')
  } catch (e) {
    error.value = `实时分析失败：${e.message}`
  } finally {
    loading.value = false
  }
}

function toggleAuto() {
  autoRefresh.value = !autoRefresh.value
  setupTimer()
}

function setupTimer() {
  if (timer) clearInterval(timer)
  timer = null
  if (!autoRefresh.value) return
  timer = setInterval(() => refreshNow(false), refreshIntervalSec * 1000)
}

onMounted(() => {
  refreshNow(false)
  setupTimer()
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.advisor-page { display:flex; flex-direction:column; gap:16px; }
.advisor-hero { display:flex; justify-content:space-between; align-items:center; gap:16px; background:#1a1a2e; border:1px solid #2a2a4a; border-radius:14px; padding:20px; }
.hero-title { font-size:28px; font-weight:800; color:#fff; }
.hero-subtitle { margin-top:6px; color:#909399; }
.hero-actions { display:flex; align-items:center; gap:10px; }
.status-row { display:flex; gap:18px; color:#909399; font-size:13px; }
.main-card, .side-card { border-radius:14px; }
.card-header { display:flex; justify-content:space-between; align-items:center; font-weight:700; }
.muted { color:#909399; font-size:12px; }
.pick-main { display:flex; flex-direction:column; gap:16px; }
.pick-top { display:flex; justify-content:space-between; align-items:flex-start; gap:16px; }
.stock-name { font-size:34px; font-weight:900; color:#fff; }
.stock-code { margin-top:4px; color:#909399; }
.price-box { text-align:right; }
.price-label { color:#909399; font-size:12px; }
.live-price { font-size:30px; font-weight:900; }
.order-plan { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:12px; }
.plan-cell { background:#16162a; border:1px solid #2a2a4a; border-radius:12px; padding:14px; }
.plan-cell.primary { border-color:#409eff; background:#10233d; }
.plan-cell.danger { border-color:#f56c6c; }
.plan-cell.target { border-color:#67c23a; }
.plan-cell.evolve { border-color:#409eff; background:#111d33; }
.plan-label { color:#909399; font-size:12px; margin-bottom:8px; }
.plan-value { font-size:24px; font-weight:900; color:#fff; }
.plan-value.small { font-size:18px; }
.plan-sub { margin-top:6px; color:#909399; font-size:12px; }
.summary-line { border-left:4px solid #409eff; background:#111827; padding:12px 14px; border-radius:8px; color:#e5e7eb; line-height:1.7; }
.reasons-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
.reason-block { background:#16162a; border-radius:12px; padding:14px; }
.reason-block.warning { border:1px solid #f56c6c55; }
.block-title { font-weight:700; margin-bottom:8px; color:#fff; }
ul { padding-left:18px; color:#cfd3dc; line-height:1.8; }
.signal-strip { display:flex; flex-wrap:wrap; gap:8px; }
.candidate-list { display:flex; flex-direction:column; gap:10px; }
.candidate-item { display:flex; align-items:center; gap:10px; padding:10px; border:1px solid #2a2a4a; border-radius:10px; cursor:pointer; background:#16162a; }
.candidate-item.active { border-color:#409eff; background:#10233d; }
.rank { width:26px; height:26px; border-radius:50%; background:#2a2a4a; display:flex; align-items:center; justify-content:center; font-weight:800; }
.candidate-info { flex:1; }
.candidate-name { font-weight:700; color:#fff; }
.candidate-code { color:#909399; font-size:12px; }
.candidate-right { text-align:right; font-size:13px; }
.up { color:#f56c6c; }
.down { color:#67c23a; }
@media (max-width: 1100px) {
  .order-plan { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .reasons-grid { grid-template-columns:1fr; }
}
</style>
