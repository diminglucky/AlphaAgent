<template>
  <div>
    <!-- Place order form -->
    <el-card shadow="never" style="border-radius:8px; margin-bottom:20px">
      <template #header><span style="font-weight:600">📤 提交订单</span></template>
      <el-form :model="form" inline label-width="70px">
        <el-form-item label="代码">
          <el-select v-model="form.symbol" style="width:160px">
            <el-option v-for="s in SYMBOLS" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="方向">
          <el-radio-group v-model="form.side">
            <el-radio-button value="BUY">买入</el-radio-button>
            <el-radio-button value="SELL">卖出</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="数量">
          <el-input-number v-model="form.quantity" :min="100" :step="100" style="width:130px" />
        </el-form-item>
        <el-form-item label="价格">
          <el-input-number v-model="form.price" :precision="2" :step="0.01" style="width:130px" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.order_type" style="width:100px">
            <el-option value="LIMIT" label="限价" />
            <el-option value="MARKET" label="市价" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="placing" @click="place">提交</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- Orders table -->
    <el-card shadow="never" style="border-radius:8px">
      <template #header>
        <span style="font-weight:600">📋 订单列表</span>
        <el-button link style="float:right" @click="load">刷新</el-button>
      </template>
      <el-table :data="orders" v-loading="loading" size="small" stripe>
        <el-table-column prop="order_id" label="订单号" width="200" show-overflow-tooltip />
        <el-table-column prop="symbol" label="代码" width="110" />
        <el-table-column label="方向" width="70">
          <template #default="{ row }">
            <el-tag :type="row.side === 'BUY' ? 'danger' : 'success'" size="small">
              {{ row.side === 'BUY' ? '买入' : '卖出' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="quantity" label="委托量" width="80" />
        <el-table-column prop="filled_quantity" label="成交量" width="80" />
        <el-table-column prop="price" label="委托价" />
        <el-table-column prop="avg_fill_price" label="成交均价" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button
              v-if="['PENDING', 'SUBMITTED', 'PARTIAL_FILLED'].includes(row.status)"
              link type="danger" size="small"
              @click="cancel(row.order_id)"
            >撤单</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && orders.length === 0" description="暂无订单" :image-size="80" />
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api.js'

const SYMBOLS = [
  { value: '600519.SH', label: '600519 茅台' },
  { value: '000001.SZ', label: '000001 平安银行' },
  { value: '300750.SZ', label: '300750 宁德时代' },
  { value: '000858.SZ', label: '000858 五粮液' },
]

const form = ref({ symbol: '600519.SH', side: 'BUY', quantity: 100, price: 1720.0, order_type: 'LIMIT' })
const placing = ref(false)
const loading = ref(false)
const orders = ref([])

const statusLabel = s => ({
  PENDING: '待处理', SUBMITTED: '已报', PARTIAL_FILLED: '部分成交',
  FILLED: '全部成交', CANCELLED: '已撤', REJECTED: '已拒绝',
}[s] || s)

const statusType = s => ({
  PENDING: 'warning', SUBMITTED: 'primary', PARTIAL_FILLED: 'warning',
  FILLED: 'success', CANCELLED: 'info', REJECTED: 'danger',
}[s] || 'info')

const place = async () => {
  placing.value = true
  try {
    await api.placeOrder(form.value)
    ElMessage.success('订单已提交')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    placing.value = false
  }
}

const cancel = async (id) => {
  await ElMessageBox.confirm('确认撤销该订单？', '撤单确认', { type: 'warning' })
  try {
    await api.cancelOrder(id)
    ElMessage.success('撤单成功')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

const load = async () => {
  loading.value = true
  try {
    const data = await api.liveOrders()
    orders.value = Array.isArray(data) ? data : (data.orders ?? [])
  } catch {
    orders.value = []
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>
