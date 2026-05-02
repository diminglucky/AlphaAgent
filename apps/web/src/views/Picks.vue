<template>
  <div>
    <!-- Sell warnings (top priority) -->
    <el-card shadow="never" style="border-radius:8px; margin-bottom:20px"
             v-if="monitor && monitor.alerts.length > 0">
      <template #header>
        <span style="font-weight:600; color:#f5222d">🚨 持仓预警 ({{ monitor.alerts.length }})</span>
        <span style="float:right; font-size:12px; color:#999">
          {{ monitor.positions_checked }} 个持仓 · 每 30s 监控 · 最后扫描 {{ fmtTime(monitor.generated_at) }}
        </span>
      </template>
      <el-table :data="monitor.alerts" size="small" stripe>
        <el-table-column label="紧急" width="90">
          <template #default="{ row }">
            <el-tag :type="urgencyTag(row.urgency)" size="small">
              {{ urgencyLabel(row.urgency) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" width="120" />
        <el-table-column prop="symbol" label="代码" width="120" />
        <el-table-column label="盈亏" width="110">
          <template #default="{ row }">
            <span :style="{ color: row.pct_pnl >= 0 ? '#f5222d' : '#52c41a', fontWeight:600 }">
              {{ (row.pct_pnl * 100).toFixed(2) }}%
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="last_price" label="现价" width="90">
          <template #default="{ row }">¥{{ row.last_price.toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="规则" width="130">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ ruleLabel(row.rule) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="message" label="提示" show-overflow-tooltip />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button size="small" type="danger" plain @click="quickSell(row)">
              📤 卖出
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Top picks -->
    <el-row :gutter="16">
      <el-col :span="14">
        <el-card shadow="never" style="border-radius:8px">
          <template #header>
            <span style="font-weight:600">📈 今日 Top 买入推荐</span>
            <el-tag v-if="scan?.agent" size="small"
                    :type="scan.agent.llm_powered ? 'primary' : 'info'"
                    style="margin-left:8px">
              {{ scan.agent.llm_powered ? '🧠 LLM Agent' : '⚙️ Agent' }} ·
              {{ scan.agent.tool_calls_made }} tools · {{ scan.agent.duration_ms }}ms
            </el-tag>
            <span style="float:right">
              <span style="font-size:12px; color:#999; margin-right:12px">
                <span v-if="scan">扫描宇宙 {{ scan.universe_size }} · 成功 {{ scan.successful }}</span>
                <span v-else>等待数据...</span>
              </span>
              <el-button size="small" @click="loadFresh">🔄 立即扫描</el-button>
              <el-button size="small" link @click="$router.push('/agents')">查看 Agent</el-button>
            </span>
          </template>
          <el-table v-if="scan" :data="scan.top_buy" size="small" stripe>
            <el-table-column type="index" width="50" />
            <el-table-column prop="name" label="名称" width="110" />
            <el-table-column prop="symbol" label="代码" width="110" />
            <el-table-column label="得分" width="80">
              <template #default="{ row }">
                <span :style="{ color: row.score > 0 ? '#f5222d' : '#52c41a', fontWeight:600 }">
                  {{ row.score >= 0 ? '+' : '' }}{{ row.score.toFixed(3) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="现价" width="80">
              <template #default="{ row }">¥{{ row.last_close.toFixed(2) }}</template>
            </el-table-column>
            <el-table-column prop="reason" label="选中理由" show-overflow-tooltip />
            <el-table-column label="操作" width="140">
              <template #default="{ row }">
                <el-button size="small" type="primary" plain @click="quickBuy(row)">
                  💰 买入
                </el-button>
                <el-button size="small" link @click="$router.push('/analysis?symbol=' + row.symbol)">
                  详情
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-else description="后台扫描中（每 2 分钟更新），可点立即扫描" :image-size="60" />
        </el-card>
      </el-col>

      <el-col :span="10">
        <el-card shadow="never" style="border-radius:8px">
          <template #header><span style="font-weight:600">📉 警惕做空风险</span></template>
          <el-table v-if="scan" :data="scan.top_sell" size="small">
            <el-table-column prop="name" label="名称" width="110" />
            <el-table-column prop="symbol" label="代码" width="110" />
            <el-table-column label="得分" width="80">
              <template #default="{ row }">
                <span :style="{ color: '#52c41a', fontWeight:600 }">{{ row.score.toFixed(3) }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="reason" label="原因" show-overflow-tooltip />
          </el-table>
          <el-empty v-else description="无数据" :image-size="60" />
        </el-card>
      </el-col>
    </el-row>

    <!-- Quick order dialog -->
    <el-dialog v-model="orderDialog.open" :title="orderDialog.title" width="500px">
      <el-form label-width="90px">
        <el-form-item label="代码">{{ orderDialog.symbol }} ({{ orderDialog.name }})</el-form-item>
        <el-form-item label="方向">
          <el-tag :type="orderDialog.side === 'BUY' ? 'danger' : 'success'">
            {{ orderDialog.side === 'BUY' ? '买入' : '卖出' }}
          </el-tag>
        </el-form-item>
        <el-form-item label="价格">
          <el-input-number v-model="orderDialog.price" :precision="2" :step="0.01" style="width:160px" />
        </el-form-item>
        <el-form-item label="数量">
          <el-input-number v-model="orderDialog.quantity" :step="100" :min="100" style="width:160px" />
          <span style="margin-left:12px; color:#888; font-size:12px">必须 100 股倍数</span>
        </el-form-item>
        <el-form-item label="预估金额">
          <span style="font-size:16px; font-weight:600">
            ¥{{ (orderDialog.price * orderDialog.quantity).toLocaleString('zh-CN') }}
          </span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="orderDialog.open = false">取消</el-button>
        <el-button type="primary" @click="submitOrder" :loading="orderDialog.submitting">
          确认下单
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, openStream } from '../api.js'

const scan = ref(null)
const monitor = ref(null)
let stopScan = null
let stopMonitor = null

const fmtTime = (iso) => iso ? new Date(iso).toLocaleTimeString('zh-CN') : '-'

const urgencyTag = (u) => ({ CRITICAL: 'danger', HIGH: 'warning', MEDIUM: 'info' }[u] || 'info')
const urgencyLabel = (u) => ({ CRITICAL: '紧急', HIGH: '高', MEDIUM: '中' }[u] || u)
const ruleLabel = (r) => ({
  stop_loss: '止损线',
  trailing_drawdown: '高位回撤',
  trend_break: '破位',
  rsi_reversal: 'RSI反转',
  bad_news: '利空',
  take_profit: '止盈',
}[r] || r)

const loadFresh = async () => {
  try {
    ElMessage.info('正在扫描全市场...')
    const data = await api.scannerFresh(true)
    scan.value = data
    ElMessage.success(`已扫描 ${data.successful} 只`)
  } catch (e) {
    ElMessage.error(e.message)
  }
}

const orderDialog = ref({
  open: false, title: '', side: 'BUY', symbol: '', name: '',
  price: 0, quantity: 100, submitting: false,
})

const quickBuy = (row) => {
  orderDialog.value = {
    open: true,
    title: `买入 ${row.name}`,
    side: 'BUY',
    symbol: row.symbol,
    name: row.name,
    price: row.last_close,
    quantity: 100,
    submitting: false,
  }
}

const quickSell = (row) => {
  if (row.available_quantity === 0) {
    ElMessage.warning('T+1 限制：买入当日不可卖出')
    return
  }
  orderDialog.value = {
    open: true,
    title: `卖出 ${row.name}`,
    side: 'SELL',
    symbol: row.symbol,
    name: row.name,
    price: row.last_price,
    quantity: row.available_quantity,
    submitting: false,
  }
}

const submitOrder = async () => {
  const o = orderDialog.value
  o.submitting = true
  try {
    await api.placeOrder({
      symbol: o.symbol, side: o.side, order_type: 'LIMIT',
      price: o.price, quantity: o.quantity, source: 'MANUAL',
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
  // Load cached snapshots
  try { scan.value = await api.scannerLatest() } catch {}
  try { monitor.value = await api.monitorLatest() } catch {}

  // Subscribe to live updates via /ws/picks
  stopScan = openStream('picks', (msg) => {
    if (msg.type === 'scan') scan.value = msg.data
    else if (msg.type === 'monitor') monitor.value = msg.data
    else if (msg.type === 'sell_alerts') {
      // Refresh full monitor list
      api.monitorLatest().then(d => monitor.value = d).catch(() => {})
    }
  })
})

onUnmounted(() => {
  if (stopScan) stopScan()
  if (stopMonitor) stopMonitor()
})
</script>
