<template>
  <div>
    <el-alert
      title="你现在只需要两件事：找最值得买的股票，找最该卖的持仓。"
      type="success"
      :closable="false"
      show-icon
      style="margin-bottom:16px"
    />

    <el-row :gutter="16">
      <el-col :span="12">
        <el-card shadow="never" style="border-radius:10px; min-height:520px">
          <template #header>
            <div style="display:flex; align-items:center; justify-content:space-between">
              <div>
                <div style="font-size:18px; font-weight:700">买入</div>
                <div style="font-size:12px; color:#999; margin-top:4px">从实时行情里找潜力最大的股票</div>
              </div>
              <el-button type="primary" @click="runBuy" :loading="buyLoading">找最值得买的股票</el-button>
            </div>
          </template>

          <el-empty v-if="!bestBuy" description="点击右上角按钮开始分析" :image-size="80" />

          <div v-else>
            <el-card shadow="never" style="margin-bottom:14px; background:#f8fbff; border:1px solid #d9ecff">
              <div style="display:flex; align-items:flex-start; justify-content:space-between; gap:12px">
                <div>
                  <div style="font-size:22px; font-weight:700; color:#1d39c4">{{ bestBuy.name || '-' }}</div>
                  <div style="font-size:14px; color:#666; margin-top:4px">{{ bestBuy.symbol }}</div>
                </div>
                <el-tag type="danger" size="large">首选买入</el-tag>
              </div>

              <el-row :gutter="12" style="margin-top:16px">
                <el-col :span="8">
                  <div class="metric-card">
                    <div class="metric-label">现价</div>
                    <div class="metric-value">¥{{ fmtPrice(bestBuy.last_close) }}</div>
                  </div>
                </el-col>
                <el-col :span="8">
                  <div class="metric-card">
                    <div class="metric-label">评分</div>
                    <div class="metric-value" style="color:#f5222d">{{ fmtScore(bestBuy.score) }}</div>
                  </div>
                </el-col>
                <el-col :span="8">
                  <div class="metric-card">
                    <div class="metric-label">建议数量</div>
                    <div class="metric-value">{{ buyQuantity(bestBuy) }} 股</div>
                  </div>
                </el-col>
              </el-row>

              <div style="margin-top:16px">
                <div style="font-size:13px; color:#999; margin-bottom:6px">买入理由</div>
                <div style="font-size:14px; line-height:1.7; color:#333">{{ bestBuy.reason || '无' }}</div>
              </div>

              <div style="margin-top:16px">
                <el-button type="primary" @click="quickBuy(bestBuy)">按建议买入</el-button>
                <el-button @click="$router.push('/analysis?symbol=' + bestBuy.symbol)">查看详情</el-button>
              </div>
            </el-card>

            <el-collapse v-if="buyList.length > 1" style="margin-top:12px">
              <el-collapse-item title="查看其他备选股票" name="buy_more">
                <el-table :data="buyList.slice(1, 5)" size="small" stripe>
                  <el-table-column prop="name" label="名称" width="110" />
                  <el-table-column prop="symbol" label="代码" width="120" />
                  <el-table-column label="现价" width="90">
                    <template #default="{ row }">¥{{ fmtPrice(row.last_close) }}</template>
                  </el-table-column>
                  <el-table-column label="评分" width="90">
                    <template #default="{ row }">{{ fmtScore(row.score) }}</template>
                  </el-table-column>
                  <el-table-column prop="reason" label="理由" show-overflow-tooltip />
                </el-table>
              </el-collapse-item>
            </el-collapse>
          </div>
        </el-card>
      </el-col>

      <el-col :span="12">
        <el-card shadow="never" style="border-radius:10px; min-height:520px">
          <template #header>
            <div style="display:flex; align-items:center; justify-content:space-between">
              <div>
                <div style="font-size:18px; font-weight:700">卖出</div>
                <div style="font-size:12px; color:#999; margin-top:4px">从当前持仓里找风险最大的股票</div>
              </div>
              <el-button type="danger" @click="runSell" :loading="sellLoading">找最该卖的股票</el-button>
            </div>
          </template>

          <el-empty v-if="!bestSell && !sellChecked" description="点击右上角按钮开始分析" :image-size="80" />
          <el-empty v-else-if="!bestSell && sellChecked" description="当前没有明显高风险持仓" :image-size="80" />

          <div v-else>
            <el-card shadow="never" style="margin-bottom:14px; background:#fffaf8; border:1px solid #ffe7d1">
              <div style="display:flex; align-items:flex-start; justify-content:space-between; gap:12px">
                <div>
                  <div style="font-size:22px; font-weight:700; color:#cf1322">{{ bestSell.name || '-' }}</div>
                  <div style="font-size:14px; color:#666; margin-top:4px">{{ bestSell.symbol }}</div>
                </div>
                <el-tag :type="sellTag(bestSell.urgency)">{{ sellLabel(bestSell.urgency) }}</el-tag>
              </div>

              <el-row :gutter="12" style="margin-top:16px">
                <el-col :span="8">
                  <div class="metric-card">
                    <div class="metric-label">现价</div>
                    <div class="metric-value">¥{{ fmtPrice(bestSell.last_price) }}</div>
                  </div>
                </el-col>
                <el-col :span="8">
                  <div class="metric-card">
                    <div class="metric-label">盈亏</div>
                    <div class="metric-value" :style="{ color: (bestSell.pct_pnl || 0) >= 0 ? '#f5222d' : '#52c41a' }">
                      {{ ((bestSell.pct_pnl || 0) * 100).toFixed(2) }}%
                    </div>
                  </div>
                </el-col>
                <el-col :span="8">
                  <div class="metric-card">
                    <div class="metric-label">可卖数量</div>
                    <div class="metric-value">{{ bestSell.available_quantity || 0 }} 股</div>
                  </div>
                </el-col>
              </el-row>

              <div style="margin-top:16px">
                <div style="font-size:13px; color:#999; margin-bottom:6px">卖出理由</div>
                <div style="font-size:14px; line-height:1.7; color:#333">{{ bestSell.message || '无' }}</div>
              </div>

              <div style="margin-top:8px">
                <el-tag effect="plain">{{ ruleLabel(bestSell.rule) }}</el-tag>
              </div>

              <div style="margin-top:16px">
                <el-button type="danger" @click="quickSell(bestSell)" :disabled="!bestSell.available_quantity">按建议卖出</el-button>
                <el-button @click="$router.push('/portfolio')">查看持仓</el-button>
              </div>
            </el-card>

            <el-collapse v-if="sellList.length > 1" style="margin-top:12px">
              <el-collapse-item title="查看其他风险持仓" name="sell_more">
                <el-table :data="sellList.slice(1, 5)" size="small" stripe>
                  <el-table-column prop="name" label="名称" width="110" />
                  <el-table-column prop="symbol" label="代码" width="120" />
                  <el-table-column label="紧急程度" width="110">
                    <template #default="{ row }">
                      <el-tag :type="sellTag(row.urgency)" size="small">{{ sellLabel(row.urgency) }}</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="盈亏" width="90">
                    <template #default="{ row }">{{ ((row.pct_pnl || 0) * 100).toFixed(2) }}%</template>
                  </el-table-column>
                  <el-table-column prop="message" label="理由" show-overflow-tooltip />
                </el-table>
              </el-collapse-item>
            </el-collapse>
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
</style>
