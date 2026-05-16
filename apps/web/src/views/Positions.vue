<template>
  <div class="positions-page">
    <div class="page-header">
      <h2>持仓管理</h2>
      <el-button type="primary" @click="showDialog = true">+ 录入持仓</el-button>
    </div>

    <!-- 汇总 -->
    <div v-if="positions.length > 0" class="summary-row">
      <div class="summary-card">
        <div class="sc-label">总市值</div>
        <div class="sc-value">¥{{ totalMarketValue.toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}</div>
      </div>
      <div class="summary-card">
        <div class="sc-label">总成本</div>
        <div class="sc-value">¥{{ totalCost.toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}</div>
      </div>
      <div class="summary-card">
        <div class="sc-label">总盈亏</div>
        <div class="sc-value" :class="totalPnl >= 0 ? 'up' : 'down'">
          {{ totalPnl >= 0 ? '+' : '' }}¥{{ totalPnl.toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}
          （{{ totalPnlPct >= 0 ? '+' : '' }}{{ totalPnlPct.toFixed(2) }}%）
        </div>
      </div>
    </div>

    <!-- 持仓列表 -->
    <div class="positions-table">
      <el-table :data="positions" size="small" v-loading="loading">
        <el-table-column label="股票" width="130">
          <template #default="{ row }">
            <div style="font-weight:600">{{ row.name }}</div>
            <div style="font-size:11px;color:#606266">{{ row.symbol }}</div>
          </template>
        </el-table-column>
        <el-table-column label="持仓量" prop="quantity" width="80" align="right" />
        <el-table-column label="均价" width="90" align="right">
          <template #default="{ row }">¥{{ row.avg_cost?.toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="现价" width="90" align="right">
          <template #default="{ row }">
            <span :class="row.change_pct >= 0 ? 'up' : 'down'">
              ¥{{ row.current_price?.toFixed(2) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="今日涨跌" width="90" align="right">
          <template #default="{ row }">
            <span :class="row.change_pct >= 0 ? 'up' : 'down'">
              {{ row.change_pct >= 0 ? '+' : '' }}{{ row.change_pct?.toFixed(2) }}%
            </span>
          </template>
        </el-table-column>
        <el-table-column label="市值" width="110" align="right">
          <template #default="{ row }">¥{{ row.market_value?.toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}</template>
        </el-table-column>
        <el-table-column label="盈亏" width="130" align="right">
          <template #default="{ row }">
            <div :class="row.pnl >= 0 ? 'up' : 'down'">
              {{ row.pnl >= 0 ? '+' : '' }}¥{{ row.pnl?.toFixed(2) }}
            </div>
            <div :class="row.pnl_pct >= 0 ? 'up' : 'down'" style="font-size:11px">
              {{ row.pnl_pct >= 0 ? '+' : '' }}{{ row.pnl_pct?.toFixed(2) }}%
            </div>
          </template>
        </el-table-column>
        <el-table-column label="止损价" width="90" align="right">
          <template #default="{ row }">
            <span style="color:#f56c6c">¥{{ row.stop_loss_price?.toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="止盈价" width="90" align="right">
          <template #default="{ row }">
            <span style="color:#67c23a">¥{{ row.take_profit_price?.toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag
              :type="positionStatus(row).type"
              size="small"
              effect="dark"
            >
              {{ positionStatus(row).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button size="small" @click="editPosition(row)">编辑</el-button>
            <el-button size="small" type="danger" plain @click="deletePosition(row.symbol)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div v-if="positions.length === 0 && !loading" class="empty-tip">
        暂无持仓，点击「录入持仓」添加
      </div>
    </div>

    <!-- 录入/编辑弹窗 -->
    <el-dialog v-model="showDialog" :title="editMode ? '编辑持仓' : '录入持仓'" width="420px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="股票" v-if="!editMode">
          <el-autocomplete
            v-model="form.name"
            :fetch-suggestions="handleSearch"
            placeholder="搜索股票..."
            @select="onSelect"
            style="width:100%"
          >
            <template #default="{ item }">
              <span>{{ item.name }}</span>
              <span style="color:#909399;margin-left:8px;font-size:12px">{{ item.symbol }}</span>
            </template>
          </el-autocomplete>
        </el-form-item>
        <el-form-item label="股票" v-else>
          {{ form.name }}（{{ form.symbol }}）
        </el-form-item>
        <el-form-item label="持仓数量">
          <el-input-number v-model="form.quantity" :min="100" :step="100" style="width:100%" />
        </el-form-item>
        <el-form-item label="买入均价">
          <el-input-number v-model="form.avg_cost" :precision="2" :step="0.1" :min="0.01" style="width:100%" />
        </el-form-item>
        <el-form-item label="止损比例">
          <el-slider v-model="stopLossPct" :min="1" :max="30" :step="1" show-input />
          <div style="font-size:12px;color:#909399">跌 {{ stopLossPct }}% 触发飞书止损提醒</div>
        </el-form-item>
        <el-form-item label="止盈比例">
          <el-slider v-model="takeProfitPct" :min="5" :max="100" :step="5" show-input />
          <div style="font-size:12px;color:#909399">涨 {{ takeProfitPct }}% 触发飞书止盈提醒</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showDialog = false">取消</el-button>
        <el-button type="primary" @click="savePosition">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api.js'
import { quotesMap } from '../store.js'
import { watch } from 'vue'

const positions = ref([])
const loading = ref(false)
const showDialog = ref(false)
const editMode = ref(false)
const stopLossPct = ref(8)
const takeProfitPct = ref(20)

const form = ref({
  symbol: '',
  name: '',
  quantity: 100,
  avg_cost: 0,
})

const totalMarketValue = computed(() => positions.value.reduce((s, p) => s + (p.market_value || 0), 0))
const totalCost = computed(() => positions.value.reduce((s, p) => s + (p.cost_value || 0), 0))
const totalPnl = computed(() => totalMarketValue.value - totalCost.value)
const totalPnlPct = computed(() => totalCost.value > 0 ? totalPnl.value / totalCost.value * 100 : 0)

function positionStatus(row) {
  if (row.pnl_pct <= -row.stop_loss_pct * 100) return { type: 'danger', label: '止损' }
  if (row.pnl_pct >= row.take_profit_pct * 100) return { type: 'success', label: '止盈' }
  if (row.pnl_pct > 0) return { type: 'success', label: '盈利' }
  if (row.pnl_pct < 0) return { type: 'danger', label: '亏损' }
  return { type: 'info', label: '持平' }
}

// 实时更新持仓价格
watch(quotesMap, (map) => {
  for (const pos of positions.value) {
    const q = map[pos.symbol]
    if (q) {
      pos.current_price = q.price
      pos.change_pct = q.change_pct
      pos.market_value = q.price * pos.quantity
      pos.pnl = pos.market_value - pos.avg_cost * pos.quantity
      pos.pnl_pct = pos.avg_cost > 0 ? (q.price - pos.avg_cost) / pos.avg_cost * 100 : 0
    }
  }
}, { deep: true })

async function loadPositions() {
  loading.value = true
  try {
    positions.value = await api.positions()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

async function handleSearch(query, cb) {
  if (!query) return cb([])
  try {
    const results = await api.search(query)
    cb(results.map(r => ({ ...r, value: r.name })))
  } catch (e) { cb([]) }
}

function onSelect(item) {
  form.value.symbol = item.symbol
  form.value.name = item.name
}

function editPosition(row) {
  editMode.value = true
  form.value = { symbol: row.symbol, name: row.name, quantity: row.quantity, avg_cost: row.avg_cost }
  stopLossPct.value = Math.round(row.stop_loss_pct * 100)
  takeProfitPct.value = Math.round(row.take_profit_pct * 100)
  showDialog.value = true
}

async function savePosition() {
  if (!form.value.symbol) {
    ElMessage.warning('请选择股票')
    return
  }
  try {
    await api.upsertPosition({
      ...form.value,
      stop_loss_pct: stopLossPct.value / 100,
      take_profit_pct: takeProfitPct.value / 100,
    })
    ElMessage.success('持仓已保存')
    showDialog.value = false
    editMode.value = false
    await loadPositions()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function deletePosition(symbol) {
  try {
    await ElMessageBox.confirm('确认删除此持仓？', '提示', { type: 'warning' })
    await api.deletePosition(symbol)
    positions.value = positions.value.filter(p => p.symbol !== symbol)
    ElMessage.success('已删除')
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e.message)
  }
}

onMounted(loadPositions)
</script>

<style scoped>
.positions-page { display: flex; flex-direction: column; gap: 20px; }

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.page-header h2 { font-size: 20px; font-weight: 700; }

.summary-row {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

.summary-card {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  padding: 16px 24px;
  min-width: 180px;
}
.sc-label { font-size: 12px; color: #606266; margin-bottom: 6px; }
.sc-value { font-size: 20px; font-weight: 700; }

.positions-table {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  padding: 16px;
}

.empty-tip {
  text-align: center;
  color: #606266;
  padding: 40px;
  font-size: 14px;
}
</style>
