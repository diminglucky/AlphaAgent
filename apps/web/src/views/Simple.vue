 <template>
  <div class="simple-page">
    <div class="hero-card">
      <div>
        <div class="hero-title">今天怎么操作</div>
        <div class="hero-subtitle">只回答两个问题：买哪只，卖哪只。</div>
      </div>
      <div class="hero-actions">
        <el-button type="primary" size="large" @click="runBuy" :loading="buyLoading">今天买什么</el-button>
        <el-button type="danger" size="large" @click="runSell" :loading="sellLoading">今天卖什么</el-button>
      </div>
    </div>

    <el-row :gutter="16">
      <el-col :span="12">
        <el-card shadow="never" class="decision-card buy-card">
          <div class="decision-header">
            <div>
              <div class="decision-title">买入建议</div>
              <div class="decision-subtitle">从实时行情里找潜力最大的股票</div>
            </div>
            <el-tag type="danger">只看第一名</el-tag>
          </div>

          <el-empty v-if="!bestBuy" description="点击“今天买什么”" :image-size="72" />

          <div v-else class="decision-body">
            <div class="decision-name">{{ bestBuy.name || '-' }}</div>
            <div class="decision-symbol">{{ bestBuy.symbol }}</div>

            <div class="metric-grid">
              <div class="metric-card">
                <div class="metric-label">现价</div>
                <div class="metric-value">¥{{ fmtPrice(bestBuy.last_close) }}</div>
              </div>
              <div class="metric-card">
                <div class="metric-label">评分</div>
                <div class="metric-value metric-up">{{ fmtScore(bestBuy.score) }}</div>
              </div>
              <div class="metric-card">
                <div class="metric-label">建议数量</div>
                <div class="metric-value">{{ buyQuantity(bestBuy) }} 股</div>
              </div>
            </div>

            <div class="reason-box">
              <div class="reason-label">买入理由</div>
              <div class="reason-text">{{ bestBuy.reason || '无' }}</div>
            </div>

            <div class="action-row">
              <el-button type="primary" @click="quickBuy(bestBuy)">按建议买入</el-button>
              <el-button @click="$router.push('/analysis?symbol=' + bestBuy.symbol)">查看详情</el-button>
            </div>
          </div>
        </el-card>
      </el-col>

      <el-col :span="12">
        <el-card shadow="never" class="decision-card sell-card">
          <div class="decision-header">
            <div>
              <div class="decision-title">卖出建议</div>
              <div class="decision-subtitle">从当前持仓里找风险最大的股票</div>
            </div>
            <el-tag type="warning">只看第一名</el-tag>
          </div>

          <el-empty v-if="!bestSell && !sellChecked" description="点击“今天卖什么”" :image-size="72" />
          <el-empty v-else-if="!bestSell && sellChecked" description="当前没有明显高风险持仓" :image-size="72" />

          <div v-else class="decision-body">
            <div style="display:flex; align-items:center; justify-content:space-between; gap:12px">
              <div>
                <div class="decision-name">{{ bestSell.name || '-' }}</div>
                <div class="decision-symbol">{{ bestSell.symbol }}</div>
              </div>
              <el-tag :type="sellTag(bestSell.urgency)">{{ sellLabel(bestSell.urgency) }}</el-tag>
            </div>

            <div class="metric-grid">
              <div class="metric-card">
                <div class="metric-label">现价</div>
                <div class="metric-value">¥{{ fmtPrice(bestSell.last_price) }}</div>
              </div>
              <div class="metric-card">
                <div class="metric-label">盈亏</div>
                <div class="metric-value" :style="{ color: (bestSell.pct_pnl || 0) >= 0 ? '#f5222d' : '#52c41a' }">
                  {{ ((bestSell.pct_pnl || 0) * 100).toFixed(2) }}%
                </div>
              </div>
              <div class="metric-card">
                <div class="metric-label">可卖数量</div>
                <div class="metric-value">{{ bestSell.available_quantity || 0 }} 股</div>
              </div>
            </div>

            <div class="reason-box">
              <div class="reason-label">卖出理由</div>
              <div class="reason-text">{{ bestSell.message || '无' }}</div>
            </div>

            <div style="margin-top:10px">
              <el-tag effect="plain">{{ ruleLabel(bestSell.rule) }}</el-tag>
            </div>

            <div class="action-row">
              <el-button type="danger" @click="quickSell(bestSell)" :disabled="!bestSell.available_quantity">按建议卖出</el-button>
              <el-button @click="$router.push('/portfolio')">查看持仓</el-button>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="orderDialog.open" :title="orderDialog.title" width="500px">
      <el-form label-width="90px">
        <el-form-item label="代码">{{ orderDialog.symbol }} ({{ orderDialog.name }})</el-form-item>
        <el-form-item label="方向">
          <el-tag :type="orderDialog.side === 'BUY' ? 'danger' : 'success'">
            {{ orderDialog.side === 'BUY' ? '买入' : '卖出' }}
          </el-tag>
        </el-form-item>
        <el-form-item label="价格">
          <el-input-number v-model="orderDialog.price" :precision="2" :step="0.01" style="width:180px" />
        </el-form-item>
        <el-form-item label="数量">
          <el-input-number v-model="orderDialog.quantity" :step="100" :min="100" style="width:180px" />
        </el-form-item>
        <el-form-item label="金额">
          <span style="font-size:16px; font-weight:700">¥{{ (orderDialog.price * orderDialog.quantity).toLocaleString('zh-CN') }}</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="orderDialog.open = false">取消</el-button>
        <el-button type="primary" @click="submitOrder" :loading="orderDialog.submitting">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api.js'

const buyLoading = ref(false)
const sellLoading = ref(false)
const buyResult = ref(null)
const sellResult = ref(null)
const sellChecked = ref(false)

const orderDialog = ref({
  open: false,
  title: '',
  side: 'BUY',
  symbol: '',
  name: '',
  price: 0,
  quantity: 100,
  submitting: false,
})

const buyList = computed(() => buyResult.value?.top_buy || [])
const bestBuy = computed(() => buyList.value[0] || null)

const urgencyRank = { CRITICAL: 3, HIGH: 2, MEDIUM: 1 }
const sellList = computed(() => {
  const alerts = sellResult.value?.alerts || []
  return [...alerts].sort((a, b) => {
    const ua = urgencyRank[a.urgency] || 0
    const ub = urgencyRank[b.urgency] || 0
    if (ua !== ub) return ub - ua
    return Math.abs(b.pct_pnl || 0) - Math.abs(a.pct_pnl || 0)
  })
})
const bestSell = computed(() => sellList.value[0] || null)

const fmtPrice = (v) => Number(v || 0).toFixed(2)
const fmtScore = (v) => {
  const n = Number(v || 0)
  return `${n >= 0 ? '+' : ''}${n.toFixed(3)}`
}
const buyQuantity = (row) => {
  const price = Number(row?.last_close || 0)
  if (!price) return 100
  return Math.max(100, Math.round((20000 / price) / 100) * 100)
}
const sellTag = (u) => ({ CRITICAL: 'danger', HIGH: 'warning', MEDIUM: 'info' }[u] || 'info')
const sellLabel = (u) => ({ CRITICAL: '立即处理', HIGH: '尽快处理', MEDIUM: '关注' }[u] || '关注')
const ruleLabel = (r) => ({
  stop_loss: '止损线',
  trailing_drawdown: '高位回撤',
  trend_break: '趋势破位',
  rsi_reversal: 'RSI反转',
  bad_news: '利空新闻',
  take_profit: '止盈',
}[r] || r || '-')

const runBuy = async () => {
  buyLoading.value = true
  try {
    buyResult.value = await api.scannerFresh(true)
    if (bestBuy.value) ElMessage.success(`首选买入：${bestBuy.value.name} ${bestBuy.value.symbol}`)
    else ElMessage.warning('没有找到合适的买入标的')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    buyLoading.value = false
  }
}

const runSell = async () => {
  sellLoading.value = true
  sellChecked.value = true
  try {
    sellResult.value = await api.monitorFresh()
    if (bestSell.value) ElMessage.warning(`优先卖出：${bestSell.value.name} ${bestSell.value.symbol}`)
    else ElMessage.success('当前没有明显高风险持仓')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    sellLoading.value = false
  }
}

const quickBuy = (row) => {
  orderDialog.value = {
    open: true,
    title: `买入 ${row.name}`,
    side: 'BUY',
    symbol: row.symbol,
    name: row.name,
    price: Number(row.last_close || 0),
    quantity: buyQuantity(row),
    submitting: false,
  }
}

const quickSell = (row) => {
  if (!row.available_quantity) {
    ElMessage.warning('当前没有可卖数量')
    return
  }
  orderDialog.value = {
    open: true,
    title: `卖出 ${row.name}`,
    side: 'SELL',
    symbol: row.symbol,
    name: row.name,
    price: Number(row.last_price || 0),
    quantity: row.available_quantity,
    submitting: false,
  }
}

const submitOrder = async () => {
  const o = orderDialog.value
  o.submitting = true
  try {
    await api.placeOrder({
      symbol: o.symbol,
      side: o.side,
      order_type: 'LIMIT',
      price: o.price,
      quantity: o.quantity,
      source: 'MANUAL',
    })
    ElMessage.success('订单已提交')
    o.open = false
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    o.submitting = false
  }
}

onMounted(async () => {
  try { buyResult.value = await api.scannerLatest() } catch {}
  try {
    sellResult.value = await api.monitorLatest()
    sellChecked.value = true
  } catch {}
})
</script>

<style scoped>
.simple-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.hero-card {
  background: linear-gradient(135deg, #ffffff 0%, #f7faff 100%);
  border: 1px solid #e6f4ff;
  border-radius: 14px;
  padding: 22px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.hero-title {
  font-size: 28px;
  font-weight: 800;
  color: #111827;
}

.hero-subtitle {
  margin-top: 6px;
  font-size: 14px;
  color: #6b7280;
}

.hero-actions {
  display: flex;
  gap: 12px;
}

.decision-card {
  border-radius: 14px;
  min-height: 420px;
}

.buy-card {
  border: 1px solid #dbeafe;
}

.sell-card {
  border: 1px solid #fde7d9;
}

.decision-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.decision-title {
  font-size: 20px;
  font-weight: 700;
  color: #111827;
}

.decision-subtitle {
  margin-top: 4px;
  font-size: 13px;
  color: #6b7280;
}

.decision-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.decision-name {
  font-size: 28px;
  font-weight: 800;
  color: #111827;
}

.decision-symbol {
  font-size: 14px;
  color: #6b7280;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.metric-card {
  background: #fff;
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  padding: 12px;
}

.metric-label {
  font-size: 12px;
  color: #999;
  margin-bottom: 6px;
}

.metric-value {
  font-size: 20px;
  font-weight: 700;
  color: #262626;
}

.metric-up {
  color: #f5222d;
}

.reason-box {
  background: #fafafa;
  border-radius: 10px;
  padding: 14px;
}

.reason-label {
  font-size: 12px;
  color: #9ca3af;
  margin-bottom: 6px;
}

.reason-text {
  font-size: 14px;
  line-height: 1.8;
  color: #374151;
}

.action-row {
  display: flex;
  gap: 10px;
}
</style>
