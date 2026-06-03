<template>
  <div class="trading-page">
    <div class="page-header">
      <div>
        <h2>交易闭环</h2>
        <p>模拟盘立即成交；切换到 QMT 模式后通过 Windows Gateway 转发。</p>
      </div>
      <div class="header-actions">
        <el-button :loading="syncing" @click="syncQmt">同步 QMT</el-button>
        <el-button :loading="loading" @click="loadAll">刷新</el-button>
      </div>
    </div>

    <div class="account-grid">
      <div class="account-card accent">
        <span>模式</span>
        <b>{{ account.mode || account.broker || 'paper' }}</b>
      </div>
      <div class="account-card">
        <span>总资产</span>
        <b>¥{{ money(account.total_asset) }}</b>
      </div>
      <div class="account-card">
        <span>可用现金</span>
        <b>¥{{ money(account.available_cash ?? account.cash) }}</b>
      </div>
      <div class="account-card">
        <span>持仓市值</span>
        <b>¥{{ money(account.market_value) }}</b>
      </div>
    </div>

    <div class="trade-layout">
      <section class="panel order-panel">
        <div class="panel-title">下单</div>
        <el-form :model="form" label-width="76px">
          <el-form-item label="股票">
            <el-autocomplete
              v-model="form.keyword"
              :fetch-suggestions="handleSearch"
              placeholder="搜索股票或输入代码"
              @select="onSelect"
              style="width:100%"
            >
              <template #default="{ item }">
                <span>{{ item.name }}</span>
                <span class="suggest-symbol">{{ item.symbol }}</span>
              </template>
            </el-autocomplete>
          </el-form-item>
          <el-form-item label="方向">
            <el-segmented v-model="form.side" :options="sideOptions" />
          </el-form-item>
          <el-form-item label="类型">
            <el-segmented v-model="form.order_type" :options="typeOptions" />
          </el-form-item>
          <el-form-item label="数量">
            <el-input-number v-model="form.quantity" :min="100" :step="100" style="width:100%" />
          </el-form-item>
          <el-form-item label="价格">
            <el-input-number
              v-model="form.price"
              :precision="2"
              :step="0.01"
              :min="0"
              style="width:100%"
              :disabled="form.order_type === 'MARKET'"
            />
          </el-form-item>
          <el-form-item label="理由">
            <el-input v-model="form.reason" type="textarea" :rows="3" placeholder="记录这笔交易的依据" />
          </el-form-item>
        </el-form>

        <div v-if="preview" class="preview-box" :class="preview.allowed ? 'ok' : 'blocked'">
          <div><b>{{ preview.allowed ? '可提交' : '被拦截' }}</b></div>
          <div>标的 {{ preview.symbol }} · {{ preview.side }} {{ preview.quantity }} 股</div>
          <div>估算金额 ¥{{ money(preview.estimated_amount) }}</div>
          <div v-if="preview.reason" class="preview-reason">{{ preview.reason }}</div>
        </div>

        <div class="order-actions">
          <el-button :loading="previewing" @click="previewOrder">预览风控</el-button>
          <el-button type="primary" :loading="placing" @click="placeOrder">
            {{ form.side === 'BUY' ? '提交买入' : '提交卖出' }}
          </el-button>
        </div>
      </section>

      <section class="panel">
        <div class="panel-title">最近订单</div>
        <el-table :data="orders" size="small" height="360">
          <el-table-column label="时间" width="130">
            <template #default="{ row }">{{ shortTime(row.submitted_at) }}</template>
          </el-table-column>
          <el-table-column label="股票" min-width="130">
            <template #default="{ row }">
              <div class="stock-name">{{ row.name || row.symbol }}</div>
              <div class="stock-symbol">{{ row.symbol }}</div>
            </template>
          </el-table-column>
          <el-table-column label="方向" width="70">
            <template #default="{ row }">
              <el-tag size="small" :type="row.side === 'BUY' ? 'danger' : 'success'" effect="dark">{{ row.side }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="数量" prop="quantity" width="80" align="right" />
          <el-table-column label="价格" width="90" align="right">
            <template #default="{ row }">{{ row.price ? row.price.toFixed(2) : '市价' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="95">
            <template #default="{ row }">
              <el-tag size="small" :type="statusType(row.status)">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </section>
    </div>

    <section class="panel">
      <div class="panel-title">当前交易持仓</div>
      <el-table :data="positions" size="small">
        <el-table-column label="股票" min-width="130">
          <template #default="{ row }">
            <div class="stock-name">{{ row.name || row.symbol }}</div>
            <div class="stock-symbol">{{ row.symbol }}</div>
          </template>
        </el-table-column>
        <el-table-column label="持仓" prop="quantity" width="90" align="right" />
        <el-table-column label="可卖" prop="available_quantity" width="90" align="right" />
        <el-table-column label="成本" width="100" align="right">
          <template #default="{ row }">¥{{ money(row.avg_cost) }}</template>
        </el-table-column>
        <el-table-column label="市值" width="130" align="right">
          <template #default="{ row }">¥{{ money(row.market_value) }}</template>
        </el-table-column>
        <el-table-column label="更新时间" width="150">
          <template #default="{ row }">{{ shortTime(row.updated_at) }}</template>
        </el-table-column>
      </el-table>
    </section>

    <section class="panel">
      <div class="panel-title">成交记录</div>
      <el-table :data="fills" size="small">
        <el-table-column label="时间" width="150">
          <template #default="{ row }">{{ shortTime(row.filled_at) }}</template>
        </el-table-column>
        <el-table-column label="股票" prop="symbol" min-width="120" />
        <el-table-column label="方向" prop="side" width="70" />
        <el-table-column label="数量" prop="quantity" width="90" align="right" />
        <el-table-column label="成交价" width="100" align="right">
          <template #default="{ row }">¥{{ money(row.price) }}</template>
        </el-table-column>
        <el-table-column label="成交额" width="130" align="right">
          <template #default="{ row }">¥{{ money(row.amount) }}</template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<script setup>
defineOptions({ name: 'Trading' })
import { onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api.js'

const loading = ref(false)
const previewing = ref(false)
const placing = ref(false)
const syncing = ref(false)
const account = ref({})
const positions = ref([])
const orders = ref([])
const fills = ref([])
const preview = ref(null)
const route = useRoute()

const sideOptions = [
  { label: '买入', value: 'BUY' },
  { label: '卖出', value: 'SELL' },
]
const typeOptions = [
  { label: '限价', value: 'LIMIT' },
  { label: '市价', value: 'MARKET' },
]

const form = reactive({
  symbol: '',
  name: '',
  keyword: '',
  side: 'BUY',
  order_type: 'LIMIT',
  quantity: 100,
  price: 0,
  reason: '',
})

async function loadAll() {
  loading.value = true
  try {
    const [a, p, o, f] = await Promise.all([
      api.tradingAccount(),
      api.tradingPositions(),
      api.tradingOrders(100),
      api.tradingFills(100),
    ])
    account.value = a || {}
    positions.value = Array.isArray(p) ? p : []
    orders.value = Array.isArray(o) ? o : []
    fills.value = Array.isArray(f) ? f : []
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

async function syncQmt() {
  syncing.value = true
  try {
    const result = await api.tradingSync(200)
    ElMessage.success(`同步完成：订单 ${result.orders_synced || 0}，新增成交 ${result.fills_created || 0}`)
    await loadAll()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    syncing.value = false
  }
}

function applyRouteQuery() {
  const q = route.query || {}
  if (q.symbol) form.symbol = String(q.symbol)
  if (q.name) form.name = String(q.name)
  if (q.symbol || q.name) form.keyword = [q.name, q.symbol].filter(Boolean).join(' ')
  if (q.side === 'BUY' || q.side === 'SELL') form.side = q.side
  if (q.price && !Number.isNaN(Number(q.price))) form.price = Number(q.price)
  if (q.reason) form.reason = String(q.reason)
}

async function handleSearch(query, cb) {
  if (!query) return cb([])
  try {
    const results = await api.search(query)
    cb(results.map(r => ({ ...r, value: `${r.name} ${r.symbol}` })))
  } catch (_) {
    cb([])
  }
}

function onSelect(item) {
  form.symbol = item.symbol
  form.name = item.name
  form.keyword = `${item.name} ${item.symbol}`
  if (item.price && !form.price) form.price = item.price
}

function payload() {
  return {
    symbol: form.symbol || form.keyword,
    name: form.name,
    side: form.side,
    order_type: form.order_type,
    quantity: form.quantity,
    price: form.order_type === 'MARKET' ? null : form.price,
    source: 'web',
    reason: form.reason,
  }
}

async function previewOrder() {
  previewing.value = true
  try {
    preview.value = await api.tradingPreview(payload())
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    previewing.value = false
  }
}

async function placeOrder() {
  if (!form.symbol && !form.keyword) {
    ElMessage.warning('请选择股票')
    return
  }
  try {
    await previewOrder()
    if (preview.value && !preview.value.allowed) return
    await ElMessageBox.confirm(
      `确认提交 ${form.side === 'BUY' ? '买入' : '卖出'} ${payload().symbol} ${form.quantity} 股？`,
      '交易确认',
      { type: form.side === 'BUY' ? 'warning' : 'info' }
    )
    placing.value = true
    const order = await api.tradingPlaceOrder(payload())
    ElMessage.success(`订单已提交：${order.status}`)
    await loadAll()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e.message)
  } finally {
    placing.value = false
  }
}

function money(v) {
  const n = Number(v || 0)
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function shortTime(v) {
  if (!v) return '-'
  const d = new Date(v)
  if (Number.isNaN(d.getTime())) return String(v)
  const text = d.toLocaleString('zh-CN', { hour12: false })
  return text.length > 5 ? text.slice(5) : text
}

function statusType(s) {
  if (s === 'FILLED') return 'success'
  if (s === 'REJECTED') return 'danger'
  if (s === 'CANCELLED') return 'info'
  if (s === 'PARTIAL') return 'warning'
  return ''
}

watch(() => route.query, applyRouteQuery, { deep: true })

onMounted(() => {
  applyRouteQuery()
  loadAll()
})
</script>

<style scoped>
.trading-page { display: flex; flex-direction: column; gap: 18px; }
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.header-actions { display: flex; gap: 8px; align-items: center; }
.page-header h2 { font-size: 20px; margin-bottom: 4px; }
.page-header p { color: #909399; font-size: 13px; }
.account-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(150px, 1fr));
  gap: 12px;
}
.account-card {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 10px;
  padding: 16px 18px;
}
.account-card.accent { border-color: rgba(64, 158, 255, 0.45); background: linear-gradient(135deg, rgba(64, 158, 255, 0.12), #1a1a2e); }
.account-card span { display: block; color: #909399; font-size: 12px; margin-bottom: 6px; }
.account-card b { font-size: 22px; color: #e0e0e0; font-family: monospace; }
.trade-layout {
  display: grid;
  grid-template-columns: 390px 1fr;
  gap: 14px;
}
.panel {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 10px;
  padding: 16px;
}
.panel-title {
  font-size: 15px;
  font-weight: 700;
  color: #e0e0e0;
  margin-bottom: 14px;
}
.suggest-symbol { color: #909399; margin-left: 8px; font-size: 12px; }
.preview-box {
  border-radius: 8px;
  padding: 12px;
  font-size: 12px;
  line-height: 1.7;
  margin-top: 8px;
}
.preview-box.ok { background: rgba(103, 194, 58, 0.10); border: 1px solid rgba(103, 194, 58, 0.35); }
.preview-box.blocked { background: rgba(245, 108, 108, 0.10); border: 1px solid rgba(245, 108, 108, 0.35); }
.preview-reason { color: #f56c6c; }
.order-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 14px;
}
.stock-name { font-weight: 600; }
.stock-symbol { font-size: 11px; color: #606266; font-family: monospace; }
@media (max-width: 980px) {
  .account-grid { grid-template-columns: 1fr 1fr; }
  .trade-layout { grid-template-columns: 1fr; }
}
@media (max-width: 560px) {
  .account-grid { grid-template-columns: 1fr; }
}
</style>
