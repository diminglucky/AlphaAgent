/**
 * Reactive realtime store — shared between Dashboard, LiveTicker,
 * Portfolio, and the alert badge.
 *
 * Subscribes to /ws/quotes, /ws/alerts and /ws/advisor exactly once
 * and exposes reactive refs for the rest of the app.
 */
import { ref, reactive, computed } from 'vue'
import { openStream, api } from './api.js'
import { ElNotification } from 'element-plus'

// ---- state ----
export const quotesMap = reactive({})       // symbol -> latest quote object
export const lastQuoteTs = ref(null)
export const connected = ref(false)

export const positions = ref([])
export const portfolioBase = ref(null)      // baseline summary from REST

export const advisorReport = ref({})        // latest cached advisor payload

export const alerts = ref([])               // most-recent first
export const unreadAlertCount = ref(0)

let started = false

// ---- derived ----
export const livePositions = computed(() =>
  positions.value.map(p => {
    const q = quotesMap[p.symbol]
    const livePrice = q?.last_price ?? (p.quantity ? p.market_value / p.quantity : p.avg_cost)
    const marketValue = livePrice * p.quantity
    const pnl = marketValue - p.avg_cost * p.quantity
    const pnlRatio = p.avg_cost > 0 ? (livePrice - p.avg_cost) / p.avg_cost : 0
    return {
      ...p,
      live_price: livePrice,
      market_value: marketValue,
      unrealized_pnl: pnl,
      pnl_ratio: pnlRatio,
      change_pct: q?.change_pct ?? 0,
    }
  })
)

export const livePortfolio = computed(() => {
  const base = portfolioBase.value
  if (!base) return null
  const liveMV = livePositions.value.reduce((s, p) => s + p.market_value, 0)
  const livePnl = livePositions.value.reduce((s, p) => s + p.unrealized_pnl, 0)
  // Today's PnL ≈ sum(qty * change)
  const dailyPnl = livePositions.value.reduce(
    (s, p) => s + (quotesMap[p.symbol]?.change ?? 0) * p.quantity, 0
  )
  return {
    ...base,
    market_value: liveMV,
    total_asset: base.cash + liveMV,
    total_pnl: livePnl,
    daily_pnl: dailyPnl,
  }
})

// ---- bootstrap ----
export async function bootstrapRealtime() {
  if (started) return
  started = true

  // 1) Load REST baseline
  try {
    const [pf, pos] = await Promise.all([api.portfolio(), api.positions()])
    portfolioBase.value = pf
    positions.value = pos
  } catch (_) { /* leave empty */ }

  // 2) Quote stream
  openStream('quotes', (msg) => {
    if (msg.type !== 'quotes') return
    connected.value = true
    lastQuoteTs.value = msg.timestamp
    for (const q of msg.data) {
      quotesMap[q.symbol] = q
    }
  })

  // 3) Alert stream
  openStream('alerts', (msg) => {
    if (msg.type !== 'alerts') return
    for (const a of msg.data) {
      alerts.value.unshift(a)
      unreadAlertCount.value++
      const tp = a.level === 'error' ? 'error' : a.level === 'success' ? 'success' : 'warning'
      ElNotification({
        title: a.title,
        message: a.body,
        type: tp,
        duration: 8000,
        position: 'top-right',
      })
    }
    // cap
    if (alerts.value.length > 50) alerts.value = alerts.value.slice(0, 50)
  })

  // 4) Advisor stream (server pushes when it refreshes)
  openStream('advisor', (msg) => {
    if (msg.type !== 'advisor' || !msg.data) return
    advisorReport.value = msg.data
  })
}

export function markAlertsRead() {
  unreadAlertCount.value = 0
}
