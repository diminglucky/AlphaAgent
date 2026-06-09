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

    <el-alert
      v-if="safetyNotice"
      :title="safetyNotice.title"
      :description="safetyNotice.description"
      :type="safetyNotice.type"
      :closable="false"
      show-icon
      class="safety-alert"
    />

    <div class="account-grid">
      <div class="account-card accent">
        <span>模式</span>
        <b>{{ accountModeLabel }}</b>
      </div>
      <div class="account-card">
        <span>总资产</span>
        <b>{{ accountMoney(account.total_asset) }}</b>
      </div>
      <div class="account-card">
        <span>可用现金</span>
        <b>{{ accountMoney(account.available_cash ?? account.cash) }}</b>
      </div>
      <div class="account-card">
        <span>持仓市值</span>
        <b>{{ accountMoney(account.market_value) }}</b>
      </div>
    </div>

    <section class="panel">
      <div class="panel-title-row">
        <div>
          <div class="panel-title">组合调仓建议</div>
          <div class="panel-subtitle">把扫描结果转成目标权重、买卖动作，并复用当前交易风控做可执行校验。</div>
        </div>
        <el-button type="primary" :loading="rebalancing" @click="loadRebalancePlan">生成建议</el-button>
      </div>

      <div class="rebalance-toolbar">
        <div class="toolbar-item">
          <span class="toolbar-label">候选数</span>
          <el-input-number v-model="rebalanceForm.top_n" :min="1" :max="30" :step="1" size="small" />
        </div>
        <div class="toolbar-item">
          <span class="toolbar-label">最低分</span>
          <el-input-number v-model="rebalanceForm.min_score" :min="0" :max="100" :step="5" size="small" />
        </div>
        <div class="toolbar-item">
          <span class="toolbar-label">候选池</span>
          <el-input-number v-model="rebalanceForm.candidate_pool" :min="1" :max="300" :step="10" size="small" />
        </div>
        <div class="toolbar-item">
          <span class="toolbar-label">周期</span>
          <el-select v-model="rebalanceForm.target_horizon_days" size="small" style="width:132px">
            <el-option :value="null" label="自动最佳" />
            <el-option :value="3" label="3 日" />
            <el-option :value="5" label="5 日" />
            <el-option :value="10" label="10 日" />
            <el-option :value="20" label="20 日" />
          </el-select>
        </div>
        <div class="toolbar-item">
          <span class="toolbar-label">配权</span>
          <el-select v-model="rebalanceForm.weighting_scheme" size="small" style="width:160px">
            <el-option label="风险调整" value="risk_adjusted" />
            <el-option label="信号比例" value="signal_proportional" />
            <el-option label="等权" value="equal_weight" />
            <el-option label="逆波动" value="inverse_volatility" />
          </el-select>
        </div>
        <div class="toolbar-switches">
          <el-switch v-model="rebalanceForm.enable_fundamental" size="small" />
          <span class="toolbar-switch-label">基本面</span>
          <el-switch v-model="rebalanceForm.enable_llm" size="small" />
          <span class="toolbar-switch-label">AI 终审</span>
        </div>
      </div>

      <div v-if="rebalancePlan" class="rebalance-result">
        <div class="rebalance-summary">
          <div class="summary-card">
            <span>候选信号</span>
            <b>{{ rebalancePlan.signals_considered || 0 }}</b>
          </div>
          <div class="summary-card">
            <span>可执行动作</span>
            <b>{{ rebalancePlan.summary?.actionable_actions || 0 }}</b>
          </div>
          <div class="summary-card">
            <span>被拦截动作</span>
            <b>{{ rebalancePlan.summary?.blocked_actions || 0 }}</b>
          </div>
          <div class="summary-card">
            <span>预期换手</span>
            <b>{{ pct(rebalancePlan.expected_turnover) }}</b>
          </div>
          <div class="summary-card">
            <span>预期现金</span>
            <b>{{ pct(rebalancePlan.expected_cash_ratio) }}</b>
          </div>
        </div>

        <div v-if="rebalancePlan.warnings?.length" class="rebalance-warnings">
          <div v-for="(warning, idx) in rebalancePlan.warnings" :key="idx" class="warning-item">
            {{ warning }}
          </div>
        </div>

        <div class="rebalance-tables">
          <div class="rebalance-table-block">
            <div class="table-block-title">目标权重</div>
            <el-table :data="rebalancePlan.target_weights || []" size="small" max-height="280">
              <el-table-column label="股票" min-width="150">
                <template #default="{ row }">
                  <div class="stock-name">{{ row.name || row.symbol }}</div>
                  <div class="stock-symbol">{{ row.symbol }}</div>
                </template>
              </el-table-column>
              <el-table-column label="行业" prop="industry" min-width="90" />
              <el-table-column label="目标权重" width="110" align="right">
                <template #default="{ row }">{{ pct(row.target_weight) }}</template>
              </el-table-column>
              <el-table-column label="胜率" width="95" align="right">
                <template #default="{ row }">{{ pct(row.probability) }}</template>
              </el-table-column>
              <el-table-column label="预期收益" width="110" align="right">
                <template #default="{ row }">{{ signedPct(row.expected_return_pct) }}</template>
              </el-table-column>
            </el-table>
          </div>

          <div class="rebalance-table-block">
            <div class="table-block-title">调仓动作</div>
            <el-table :data="rebalancePlan.actions || []" size="small" max-height="280">
              <el-table-column label="股票" min-width="150">
                <template #default="{ row }">
                  <div class="stock-name">{{ row.name || row.symbol }}</div>
                  <div class="stock-symbol">{{ row.symbol }}</div>
                </template>
              </el-table-column>
              <el-table-column label="动作" width="80">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.action === 'BUY' ? 'danger' : 'success'" effect="dark">{{ row.action }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="数量" width="90" align="right" prop="quantity" />
              <el-table-column label="目标权重" width="100" align="right">
                <template #default="{ row }">{{ pct(row.target_weight) }}</template>
              </el-table-column>
              <el-table-column label="风控" width="95">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.risk?.allowed ? 'success' : 'danger'">
                    {{ row.risk?.allowed ? '放行' : '拦截' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="96" fixed="right">
                <template #default="{ row }">
                  <el-tooltip
                    :disabled="row.risk?.allowed"
                    :content="row.risk?.reason || '该动作已被风控拦截'"
                    placement="top"
                  >
                    <span>
                      <el-button
                        size="small"
                        text
                        type="primary"
                        :disabled="!row.risk?.allowed"
                        @click="applyPlanAction(row)"
                      >
                        带入下单
                      </el-button>
                    </span>
                  </el-tooltip>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>
      </div>
    </section>

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
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api.js'

const loading = ref(false)
const previewing = ref(false)
const placing = ref(false)
const syncing = ref(false)
const rebalancing = ref(false)
const account = ref({})
const positions = ref([])
const orders = ref([])
const fills = ref([])
const preview = ref(null)
const rebalancePlan = ref(null)
const marketStatus = ref(null)
const healthStatus = ref(null)
const loadError = ref('')
const route = useRoute()
const accountAvailable = computed(() => !loadError.value && !(healthStatus.value?.auth_enabled && !healthStatus.value?.auth_configured))
const accountModeLabel = computed(() => {
  if (!accountAvailable.value) return '--'
  return account.value?.mode || account.value?.broker || 'paper'
})

const safetyNotice = computed(() => {
  if (healthStatus.value?.auth_enabled && !healthStatus.value?.auth_configured) {
    return {
      type: 'error',
      title: 'API 鉴权已开启但未配置 Key',
      description: '服务端缺少 QUANT_ADMIN_API_KEY / QUANT_TRADER_API_KEY / QUANT_VIEWER_API_KEY。当前页面无法读取真实交易状态，请先完成部署配置。',
    }
  }
  if (loadError.value) {
    return {
      type: 'error',
      title: '交易状态加载失败',
      description: loadError.value,
    }
  }
  if (account.value?.ok === false || account.value?.status === 'blocked') {
    return {
      type: 'error',
      title: 'QMT 实盘安全门禁已阻断',
      description: account.value.reason || account.value.error || '当前 QMT 配置不满足实盘条件，请先修复鉴权、行情源和 Gateway 后再交易。',
    }
  }
  if (marketStatus.value?.mock) {
    return {
      type: 'error',
      title: '当前使用 Mock 行情，不可实盘',
      description: '扫描、进化和交易风控会基于演示数据运行，只能用于功能验证，不能作为真实交易依据。',
    }
  }
  if ((account.value?.mode || account.value?.broker || 'paper') === 'paper') {
    return {
      type: 'warning',
      title: '当前是模拟盘模式',
      description: '订单只会写入本地 paper 账户，不会发送到券商。切换 QMT 前请先完成实盘安全检查。',
    }
  }
  return null
})

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

const rebalanceForm = reactive({
  top_n: 8,
  min_score: 60,
  candidate_pool: 30,
  enable_fundamental: true,
  enable_llm: false,
  llm_top_n: 8,
  target_horizon_days: null,
  weighting_scheme: 'risk_adjusted',
  use_cache: true,
})

async function loadAll() {
  loading.value = true
  loadError.value = ''
  try {
    const health = await api.health().catch(() => null)
    healthStatus.value = health
    const [accountResult, positionsResult, ordersResult, fillsResult, marketResult] = await Promise.allSettled([
      api.tradingAccount(),
      api.tradingPositions(),
      api.tradingOrders(100),
      api.tradingFills(100),
      api.cacheStatus(),
    ])
    if (accountResult.status === 'fulfilled') account.value = accountResult.value || {}
    else loadError.value = accountResult.reason?.message || '账户接口不可用'
    if (positionsResult.status === 'fulfilled') positions.value = Array.isArray(positionsResult.value) ? positionsResult.value : []
    if (ordersResult.status === 'fulfilled') orders.value = Array.isArray(ordersResult.value) ? ordersResult.value : []
    if (fillsResult.status === 'fulfilled') fills.value = Array.isArray(fillsResult.value) ? fillsResult.value : []
    if (marketResult.status === 'fulfilled') marketStatus.value = marketResult.value || null
    else if (!loadError.value) loadError.value = marketResult.reason?.message || '行情状态接口不可用'
  } catch (e) {
    loadError.value = e.message
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

async function syncQmt() {
  syncing.value = true
  try {
    const result = await api.tradingSync(200)
    if (result?.ok === false) {
      account.value = { ...(account.value || {}), ...result, status: 'blocked' }
      ElMessage.error(result.reason || 'QMT 同步被安全门禁阻断')
      return
    }
    ElMessage.success(`同步完成：订单 ${result.orders_synced || 0}，新增成交 ${result.fills_created || 0}`)
    await loadAll()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    syncing.value = false
  }
}

async function loadRebalancePlan() {
  rebalancing.value = true
  try {
    rebalancePlan.value = await api.tradingRebalancePlan({ ...rebalanceForm })
    const summary = rebalancePlan.value?.summary || {}
    if (rebalancePlan.value?.ok === false) {
      ElMessage.warning(rebalancePlan.value?.reason || '当前无法生成调仓建议')
    } else {
      ElMessage.success(`建议已生成：可执行 ${summary.actionable_actions || 0} 笔，拦截 ${summary.blocked_actions || 0} 笔`)
    }
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    rebalancing.value = false
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
    if (order.status === 'REJECTED') {
      ElMessage.error(order.error_message || '订单已被风控拒绝，未产生真实成交')
    } else {
      ElMessage.success(`订单已提交：${order.status}`)
    }
    await loadAll()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e.message)
  } finally {
    placing.value = false
  }
}

function applyPlanAction(action) {
  if (!action?.risk?.allowed) {
    ElMessage.warning(action?.risk?.reason || '该调仓动作已被风控拦截，不能带入下单')
    return
  }
  form.symbol = action.symbol
  form.name = action.name || ''
  form.keyword = [action.name, action.symbol].filter(Boolean).join(' ')
  form.side = action.action
  form.order_type = 'LIMIT'
  form.quantity = Number(action.quantity || 100)
  form.price = Number(action.price || 0)
  form.reason = action.reason || ''
  preview.value = action.risk || null
}

function money(v) {
  const n = Number(v || 0)
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function accountMoney(v) {
  if (!accountAvailable.value || v === undefined || v === null) return '--'
  return `¥${money(v)}`
}

function pct(v) {
  const n = Number(v || 0)
  return `${(n * 100).toFixed(1)}%`
}

function signedPct(v) {
  const n = Number(v || 0)
  const fixed = n.toFixed(1)
  return `${n > 0 ? '+' : ''}${fixed}%`
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
.safety-alert { border-radius: 10px; }
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
.panel-title-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 14px;
}
.panel-subtitle {
  color: #909399;
  font-size: 12px;
  line-height: 1.5;
}
.rebalance-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 16px;
  padding: 12px;
  border-radius: 10px;
  background: rgba(64, 158, 255, 0.08);
  border: 1px solid rgba(64, 158, 255, 0.15);
}
.toolbar-item {
  display: flex;
  align-items: center;
  gap: 8px;
}
.toolbar-label,
.toolbar-switch-label {
  color: #909399;
  font-size: 12px;
}
.toolbar-switches {
  display: flex;
  align-items: center;
  gap: 8px;
}
.rebalance-result {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 14px;
}
.rebalance-summary {
  display: grid;
  grid-template-columns: repeat(5, minmax(120px, 1fr));
  gap: 10px;
}
.summary-card {
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid #2a2a4a;
  border-radius: 10px;
  padding: 12px;
}
.summary-card span {
  display: block;
  color: #909399;
  font-size: 12px;
  margin-bottom: 6px;
}
.summary-card b {
  color: #e0e0e0;
  font-size: 18px;
  font-family: monospace;
}
.rebalance-warnings {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.warning-item {
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(230, 162, 60, 0.12);
  border: 1px solid rgba(230, 162, 60, 0.26);
  color: #f3d19e;
  font-size: 12px;
  line-height: 1.6;
}
.rebalance-tables {
  display: grid;
  grid-template-columns: 1fr 1.25fr;
  gap: 14px;
}
.rebalance-table-block {
  min-width: 0;
}
.table-block-title {
  color: #cfd3dc;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
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
  .rebalance-summary { grid-template-columns: 1fr 1fr; }
  .rebalance-tables { grid-template-columns: 1fr; }
  .trade-layout { grid-template-columns: 1fr; }
}
@media (max-width: 560px) {
  .account-grid { grid-template-columns: 1fr; }
  .panel-title-row { flex-direction: column; align-items: stretch; }
  .rebalance-summary { grid-template-columns: 1fr; }
}
</style>
