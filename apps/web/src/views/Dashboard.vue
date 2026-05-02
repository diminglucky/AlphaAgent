<template>
  <div>
    <!-- Live realtime ticker -->
    <LiveTicker />

    <!-- Live P&L stat cards (recompute every quote tick) -->
    <el-row :gutter="16" style="margin-bottom:20px">
      <el-col :span="6" v-for="s in stats" :key="s.label">
        <el-card shadow="never" style="border-radius:8px">
          <p style="color:#8c8c8c; font-size:13px; margin-bottom:8px">
            {{ s.label }}
            <el-tag v-if="s.live" size="small" effect="plain" type="success" style="margin-left:6px; transform:scale(0.75)">实时</el-tag>
          </p>
          <p style="font-size:22px; font-weight:700" :style="{ color: s.color || '#333' }">
            <transition name="flash" mode="out-in"><span :key="s.value">{{ s.value }}</span></transition>
          </p>
          <p v-if="s.sub" style="font-size:12px; color:#8c8c8c; margin-top:4px">{{ s.sub }}</p>
        </el-card>
      </el-col>
    </el-row>

    <!-- Live positions mini-table -->
    <el-card v-if="livePositions.length" shadow="never" style="border-radius:8px; margin-bottom:20px">
      <template #header>
        <span style="font-weight:600">📊 实时持仓盈亏</span>
        <span style="float:right; font-size:12px; color:#aaa">每 3 秒自动刷新</span>
      </template>
      <el-table :data="livePositions" size="small" stripe>
        <el-table-column prop="symbol" label="代码" width="110" />
        <el-table-column label="数量" width="100">
          <template #default="{ row }">{{ row.quantity.toLocaleString() }}</template>
        </el-table-column>
        <el-table-column label="成本">
          <template #default="{ row }">¥{{ row.avg_cost.toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="实时价">
          <template #default="{ row }">
            <transition name="flash" mode="out-in">
              <span :key="row.live_price.toFixed(2)" :style="{ color: row.change_pct >= 0 ? '#f5222d' : '#52c41a', fontWeight: 600 }">
                ¥{{ row.live_price.toFixed(2) }}
              </span>
            </transition>
          </template>
        </el-table-column>
        <el-table-column label="今日">
          <template #default="{ row }">
            <span :style="{ color: row.change_pct >= 0 ? '#f5222d' : '#52c41a' }">
              {{ row.change_pct >= 0 ? '+' : '' }}{{ row.change_pct.toFixed(2) }}%
            </span>
          </template>
        </el-table-column>
        <el-table-column label="市值">
          <template #default="{ row }">¥{{ row.market_value.toLocaleString('zh-CN', { maximumFractionDigits: 0 }) }}</template>
        </el-table-column>
        <el-table-column label="浮动盈亏">
          <template #default="{ row }">
            <span :style="{ color: row.unrealized_pnl >= 0 ? '#f5222d' : '#52c41a', fontWeight: 600 }">
              {{ row.unrealized_pnl >= 0 ? '+' : '' }}¥{{ Math.abs(row.unrealized_pnl).toLocaleString('zh-CN', { maximumFractionDigits: 0 }) }}
              ({{ row.pnl_ratio >= 0 ? '+' : '' }}{{ (row.pnl_ratio * 100).toFixed(2) }}%)
            </span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Advisor (live cached, refreshes every 60s on backend) -->
    <el-card shadow="never" style="border-radius:8px; margin-bottom:20px">
      <template #header>
        <div style="display:flex; align-items:center; justify-content:space-between">
          <span style="font-weight:600">🎯 智能交易建议</span>
          <div style="display:flex; gap:6px; align-items:center">
            <el-tag size="small" type="danger">卖出 {{ summary.sell + summary.take_profit + summary.stop_loss }}</el-tag>
            <el-tag size="small" type="success">买入 {{ summary.buy }}</el-tag>
            <el-tag size="small" type="info">持有 {{ summary.hold }}</el-tag>
            <el-button link type="primary" :loading="refreshing" @click="forceRefresh">
              <el-icon><Refresh /></el-icon> 立即刷新
            </el-button>
          </div>
        </div>
      </template>

      <el-empty v-if="!items.length" description="正在生成首份建议…（约 60 秒）" :image-size="60" />
      <div v-else>
        <el-tabs>
          <el-tab-pane :label="`🔴 急需操作 (${urgent.length})`">
            <AdvisorTable :items="urgent" />
          </el-tab-pane>
          <el-tab-pane :label="`💰 持仓建议 (${holdings.length})`">
            <AdvisorTable :items="holdings" />
          </el-tab-pane>
          <el-tab-pane :label="`✨ 买入机会 (${buys.length})`">
            <AdvisorTable :items="buys" />
          </el-tab-pane>
        </el-tabs>
      </div>

      <div v-if="advisorReport.generated_at" style="margin-top:8px; text-align:right; font-size:12px; color:#aaa">
        最近生成：{{ new Date(advisorReport.generated_at).toLocaleString('zh-CN') }} · 由多 Agent + 持仓感知引擎产生
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import LiveTicker from '../components/LiveTicker.vue'
import AdvisorTable from '../components/AdvisorTable.vue'
import { livePortfolio, livePositions, advisorReport } from '../realtimeStore.js'
import { api } from '../api.js'

const refreshing = ref(false)

const fmt = v => `¥${Number(v ?? 0).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`
const fmtPnl = v => {
  const n = Number(v ?? 0)
  return (n >= 0 ? '+' : '') + fmt(n)
}

const stats = computed(() => {
  const p = livePortfolio.value || {}
  return [
    { label: '总资产', value: fmt(p.total_asset), live: true },
    { label: '可用现金', value: fmt(p.cash) },
    { label: '持仓市值', value: fmt(p.market_value), live: true },
    {
      label: '今日盈亏',
      value: fmtPnl(p.daily_pnl),
      color: (p.daily_pnl ?? 0) >= 0 ? '#f5222d' : '#52c41a',
      sub: `累计 ${fmtPnl(p.total_pnl)}`,
      live: true,
    },
  ]
})

const items = computed(() => advisorReport.value.items || [])
const summary = computed(() => ({
  buy: 0, sell: 0, hold: 0, pass: 0, take_profit: 0, stop_loss: 0,
  ...(advisorReport.value.summary || {}),
  stop_loss: items.value.filter(i => i.action === 'STOP_LOSS').length,
}))
const urgent = computed(() => items.value.filter(i =>
  i.action === 'STOP_LOSS' || (i.action === 'SELL' && i.priority <= 2) || i.action === 'TAKE_PROFIT'
))
const holdings = computed(() => items.value.filter(i => i.held))
const buys = computed(() => items.value.filter(i => !i.held && i.action === 'BUY'))

const forceRefresh = async () => {
  refreshing.value = true
  try {
    const data = await fetch('/api/v1/advisor/recommendations?fresh=true').then(r => r.json())
    advisorReport.value = data
    ElMessage.success('已重新生成')
  } catch (e) {
    ElMessage.error('刷新失败')
  } finally {
    refreshing.value = false
  }
}

onMounted(async () => {
  // If the WS hasn't pushed an advisor report yet, fetch the cached one
  if (!advisorReport.value.items) {
    try {
      const data = await api.advisor()
      advisorReport.value = data
    } catch (_) { /* will arrive via WS soon */ }
  }
})
</script>

<style scoped>
.flash-enter-active, .flash-leave-active { transition: opacity 0.3s; }
.flash-enter-from, .flash-leave-to { opacity: 0.4; }
</style>
