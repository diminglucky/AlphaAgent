<template>
  <div class="alerts-page">
    <div class="page-header">
      <h2>提醒中心</h2>
      <div class="header-actions">
        <el-radio-group v-model="filter" size="small" @change="loadAlerts">
          <el-radio-button :value="undefined">全部</el-radio-button>
          <el-radio-button :value="false">待触发</el-radio-button>
          <el-radio-button :value="true">已触发</el-radio-button>
        </el-radio-group>
        <el-button type="primary" size="small" @click="showCreateDialog = true">+ 新建提醒</el-button>
        <el-button size="small" :icon="Refresh" @click="loadAlerts" />
      </div>
    </div>

    <!-- 实时触发的提醒 -->
    <div v-if="liveAlerts.length > 0" class="live-alerts">
      <div class="section-title">🔴 实时触发</div>
      <div v-for="a in liveAlerts" :key="a.symbol + a.reason" class="live-alert-item">
        <div class="la-symbol">{{ a.name || a.symbol }}</div>
        <div class="la-reason">{{ a.reason }}</div>
        <div class="la-price">
          当前 ¥{{ a.current_price?.toFixed(2) || a.price?.toFixed(2) }}
          <span v-if="a.pnl_pct !== undefined" :class="a.pnl_pct >= 0 ? 'up' : 'down'">
            {{ a.pnl_pct > 0 ? '+' : '' }}{{ a.pnl_pct?.toFixed(2) }}%
          </span>
        </div>
      </div>
    </div>

    <!-- 提醒列表 -->
    <div class="alerts-table">
      <el-table :data="alerts" size="small" v-loading="loading">
        <el-table-column label="股票" width="120">
          <template #default="{ row }">
            <div>{{ row.name || row.symbol }}</div>
            <div style="font-size:11px;color:#606266">{{ row.symbol }}</div>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="120">
          <template #default="{ row }">
            <el-tag :type="alertTagType(row.alert_type)" size="small" effect="dark">
              {{ alertLabel(row.alert_type) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="目标价" width="100">
          <template #default="{ row }">
            <span v-if="row.target_price">¥{{ row.target_price?.toFixed(2) }}</span>
            <span v-else style="color:#606266">—</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.triggered ? 'success' : 'warning'" size="small">
              {{ row.triggered ? '已触发' : '待触发' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="飞书" width="80">
          <template #default="{ row }">
            <el-icon v-if="row.feishu_sent" color="#67c23a"><Check /></el-icon>
            <el-icon v-else color="#606266"><Close /></el-icon>
          </template>
        </el-table-column>
        <el-table-column label="备注" min-width="160">
          <template #default="{ row }">
            <span style="font-size:12px;color:#909399">{{ row.message || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="140">
          <template #default="{ row }">{{ row.created_at?.slice(0, 16) }}</template>
        </el-table-column>
        <el-table-column label="触发时间" width="140">
          <template #default="{ row }">{{ row.triggered_at?.slice(0, 16) || '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button
              size="small"
              type="danger"
              :icon="Delete"
              circle
              plain
              @click="deleteAlert(row.id)"
            />
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 新建提醒弹窗 -->
    <el-dialog v-model="showCreateDialog" title="新建价格提醒" width="420px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="股票">
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
        <el-form-item label="提醒类型">
          <el-radio-group v-model="form.alert_type">
            <el-radio value="price_above">价格突破（涨到）</el-radio>
            <el-radio value="price_below">价格跌破（跌到）</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="目标价格">
          <el-input-number v-model="form.target_price" :precision="2" :step="0.1" style="width:100%" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.message" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="createAlert">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
defineOptions({ name: 'Alerts' })
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Delete, Check, Close } from '@element-plus/icons-vue'
import { api } from '../api.js'
import { recentAlerts, clearAlertBadge } from '../store.js'

const alerts = ref([])
const loading = ref(false)
const filter = ref(undefined)
const showCreateDialog = ref(false)
const liveAlerts = ref([])

const form = ref({
  symbol: '',
  name: '',
  alert_type: 'price_above',
  target_price: 0,
  message: '',
})

// 监听实时提醒
import { watch } from 'vue'
watch(recentAlerts, (val) => {
  liveAlerts.value = val.slice(0, 5)
}, { deep: true })

async function loadAlerts() {
  loading.value = true
  try {
    alerts.value = await api.alerts(filter.value)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

async function deleteAlert(id) {
  try {
    await ElMessageBox.confirm('确认删除此提醒？', '提示', { type: 'warning' })
    await api.deleteAlert(id)
    alerts.value = alerts.value.filter(a => a.id !== id)
    ElMessage.success('已删除')
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e.message)
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

async function createAlert() {
  if (!form.value.symbol) {
    ElMessage.warning('请选择股票')
    return
  }
  try {
    await api.createAlert(form.value)
    ElMessage.success('提醒已创建')
    showCreateDialog.value = false
    form.value = { symbol: '', name: '', alert_type: 'price_above', target_price: 0, message: '' }
    await loadAlerts()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

function alertLabel(type) {
  const map = {
    price_above: '价格突破',
    price_below: '价格跌破',
    agent_buy: 'Agent买入',
    agent_sell: 'Agent卖出',
    stop_loss: '止损',
  }
  return map[type] || type
}

function alertTagType(type) {
  if (type === 'price_above' || type === 'agent_buy') return 'success'
  if (type === 'price_below' || type === 'stop_loss' || type === 'agent_sell') return 'danger'
  return 'info'
}

onMounted(() => {
  loadAlerts()
  clearAlertBadge()
  liveAlerts.value = recentAlerts.value.slice(0, 5)
})
</script>

<style scoped>
.alerts-page { display: flex; flex-direction: column; gap: 20px; }

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}
.page-header h2 { font-size: 20px; font-weight: 700; }
.header-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }

.section-title {
  font-size: 13px;
  font-weight: 600;
  color: #909399;
  margin-bottom: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.live-alerts {
  background: #1a1a2e;
  border: 1px solid #f56c6c;
  border-radius: 8px;
  padding: 14px;
}

.live-alert-item {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 8px 0;
  border-bottom: 1px solid #2a2a4a;
  font-size: 13px;
}
.live-alert-item:last-child { border-bottom: none; }
.la-symbol { font-weight: 600; min-width: 80px; }
.la-reason { flex: 1; color: #c0c4cc; }
.la-price { color: #909399; white-space: nowrap; }

.alerts-table {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  padding: 16px;
}
</style>
