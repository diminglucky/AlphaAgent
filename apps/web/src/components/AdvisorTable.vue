<template>
  <el-table :data="items" size="small" stripe>
    <el-table-column type="expand">
      <template #default="{ row }">
        <div style="padding:8px 24px">
          <pre style="white-space:pre-wrap; font-family:inherit; font-size:13px; color:#444; line-height:1.7">{{ row.detail }}</pre>
          <div v-if="row.risk_flags?.length" style="margin-top:10px">
            <strong style="font-size:13px">风险标记：</strong>
            <el-tag v-for="f in row.risk_flags" :key="f" type="danger" size="small" style="margin:3px">
              {{ f }}
            </el-tag>
          </div>
        </div>
      </template>
    </el-table-column>
    <el-table-column prop="symbol" label="代码" width="110" />
    <el-table-column label="操作" width="110">
      <template #default="{ row }">
        <el-tag :type="actionType(row.action)" effect="dark" size="small">
          {{ actionLabel(row.action) }}
        </el-tag>
      </template>
    </el-table-column>
    <el-table-column label="优先级" width="90">
      <template #default="{ row }">
        <span :style="{ color: priorityColor(row.priority), fontWeight: 600 }">
          {{ '🔴🟠🟡🟢🔵'[row.priority - 1] || '⚪' }} {{ row.priority }}
        </span>
      </template>
    </el-table-column>
    <el-table-column prop="reason" label="建议理由" show-overflow-tooltip />
    <el-table-column label="置信度" width="100">
      <template #default="{ row }">
        <el-progress :percentage="Math.round(row.confidence * 100)" :stroke-width="4" />
      </template>
    </el-table-column>
    <el-table-column label="盈亏" width="100">
      <template #default="{ row }">
        <span v-if="row.current_pnl_ratio != null"
          :style="{ color: row.current_pnl_ratio >= 0 ? '#f5222d' : '#52c41a', fontWeight: 600 }">
          {{ row.current_pnl_ratio >= 0 ? '+' : '' }}{{ (row.current_pnl_ratio * 100).toFixed(2) }}%
        </span>
        <span v-else style="color:#bbb">–</span>
      </template>
    </el-table-column>
  </el-table>
  <el-empty v-if="!items.length" description="无建议" :image-size="60" />
</template>

<script setup>
defineProps({ items: { type: Array, default: () => [] } })

const actionLabel = a => ({
  BUY: '买入', SELL: '卖出',
  STOP_LOSS: '止损', TAKE_PROFIT: '止盈',
  HOLD: '持有', PASS: '观望',
}[a] || a)

const actionType = a => ({
  BUY: 'success',
  SELL: 'danger',
  STOP_LOSS: 'danger',
  TAKE_PROFIT: 'warning',
  HOLD: 'info',
  PASS: 'info',
}[a] || 'info')

const priorityColor = p => ({
  1: '#ff4d4f', 2: '#fa8c16', 3: '#faad14', 4: '#1890ff', 5: '#52c41a',
}[p] || '#999')
</script>
