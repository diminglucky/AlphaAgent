<template>
  <div>
    <!-- Summary stats -->
    <el-row :gutter="16" style="margin-bottom:20px">
      <el-col :span="6" v-for="s in summaryCards" :key="s.label">
        <el-card shadow="never" style="border-radius:8px">
          <p style="font-size:13px; color:#8c8c8c; margin-bottom:6px">{{ s.label }}</p>
          <p style="font-size:22px; font-weight:700" :style="{ color: s.color || '#333' }">{{ s.value }}</p>
        </el-card>
      </el-col>
    </el-row>

    <!-- Positions table -->
    <el-card shadow="never" style="border-radius:8px" v-loading="loading">
      <template #header><span style="font-weight:600">📋 持仓明细</span></template>
      <el-table :data="positions" size="small" stripe>
        <el-table-column prop="symbol" label="代码" width="120" />
        <el-table-column prop="quantity" label="持仓量" />
        <el-table-column prop="available_quantity" label="可用量" />
        <el-table-column prop="avg_cost" label="成本价">
          <template #default="{ row }">{{ fmt2(row.avg_cost) }}</template>
        </el-table-column>
        <el-table-column prop="current_price" label="现价">
          <template #default="{ row }">{{ fmt2(row.current_price) }}</template>
        </el-table-column>
        <el-table-column label="市值">
          <template #default="{ row }">{{ fmtY(row.market_value) }}</template>
        </el-table-column>
        <el-table-column label="盈亏">
          <template #default="{ row }">
            <span :style="{ color: row.unrealized_pnl >= 0 ? '#f5222d' : '#52c41a', fontWeight: 600 }">
              {{ row.unrealized_pnl >= 0 ? '+' : '' }}{{ fmtY(row.unrealized_pnl) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="盈亏率">
          <template #default="{ row }">
            <span :style="{ color: row.pnl_ratio >= 0 ? '#f5222d' : '#52c41a' }">
              {{ row.pnl_ratio >= 0 ? '+' : '' }}{{ (row.pnl_ratio * 100).toFixed(2) }}%
            </span>
          </template>
        </el-table-column>
        <el-table-column label="仓位占比">
          <template #default="{ row }">
            <el-progress
              :percentage="Math.round((row.weight ?? 0) * 100)"
              :stroke-width="6"
              :show-text="false"
              style="width:80px; display:inline-block"
            />
            <span style="font-size:12px; margin-left:6px; color:#555">
              {{ ((row.weight ?? 0) * 100).toFixed(1) }}%
            </span>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && positions.length === 0" description="暂无持仓" :image-size="80" />
    </el-card>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { livePortfolio, livePositions } from '../realtimeStore.js'

const loading = computed(() => livePositions.value.length === 0)

const fmt2 = v => Number(v ?? 0).toFixed(2)
const fmtY = v => `¥${Number(v ?? 0).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`
const fmtPnl = v => {
  const n = Number(v ?? 0)
  return (n >= 0 ? '+' : '') + fmtY(n)
}

const summaryCards = computed(() => {
  const p = livePortfolio.value || {}
  return [
    { label: '总资产', value: fmtY(p.total_asset) },
    { label: '可用现金', value: fmtY(p.cash) },
    { label: '持仓市值', value: fmtY(p.market_value) },
    {
      label: '累计盈亏',
      value: fmtPnl(p.total_pnl),
      color: (p.total_pnl ?? 0) >= 0 ? '#f5222d' : '#52c41a',
    },
  ]
})

const positions = computed(() => {
  const rawList = livePositions.value
  const totalMV = rawList.reduce((s, p) => s + (p.market_value || 0), 0) || 1
  return rawList.map(p => ({
    ...p,
    current_price: p.live_price,
    weight: p.market_value / totalMV,
  }))
})
</script>
