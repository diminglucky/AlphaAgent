/**
 * 全局响应式状态
 */
import { reactive, ref } from 'vue'
import { ElNotification } from 'element-plus'
import { openStream } from './api.js'

// 行情数据 symbol -> quote
export const quotesMap = reactive({})
export const wsConnected = ref(false)
export const lastQuoteTime = ref('')   // 最后收到行情的时间
export const unreadAlerts = ref(0)
export const recentAlerts = ref([])

let _started = false

export function initStreams() {
  if (_started) return
  _started = true

  // 行情流
  openStream('quotes', (msg) => {
    if (msg.type !== 'quotes') return
    wsConnected.value = true
    const now = new Date()
    lastQuoteTime.value = now.toLocaleTimeString('zh-CN', { hour12: false })
    for (const q of msg.data || []) {
      quotesMap[q.symbol] = q
    }
  })

  // 提醒流
  openStream('alerts', (msg) => {
    if (msg.type !== 'alerts') return
    for (const a of msg.data || []) {
      unreadAlerts.value++
      recentAlerts.value.unshift(a)
      if (recentAlerts.value.length > 50) recentAlerts.value.pop()

      const isStop = a.reason?.includes('止损') || (a.pnl_pct != null && a.pnl_pct < -5)
      ElNotification({
        title: isStop ? '⚠️ 止损提醒' : '📢 价格提醒',
        message: a.reason || `${a.name || a.symbol} 触发提醒`,
        type: isStop ? 'error' : 'warning',
        duration: 10000,
        position: 'top-right',
      })
    }
  })
}

export function clearAlertBadge() {
  unreadAlerts.value = 0
}

export function getLivePrice(symbol) {
  return quotesMap[symbol]?.price ?? 0
}
