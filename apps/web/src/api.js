import axios from 'axios'

export const http = axios.create({
  baseURL: '/api/v1',
  timeout: 15000,
})

http.interceptors.response.use(
  res => res.data,
  err => {
    const msg = err.response?.data?.detail || err.message || '请求失败'
    return Promise.reject(new Error(msg))
  }
)

export const api = {
  // ---------- health ----------
  health: () => http.get('/health'),

  // ---------- market ----------
  instruments: () => http.get('/market/instruments'),
  quotes: (symbols) => http.get('/market/quotes/realtime', { params: { symbols: symbols.join(',') } }),
  bars: (symbol, freq = '1d') => http.get('/market/bars', { params: { symbol, freq } }),

  // ---------- portfolio ----------
  portfolio: () => http.get('/portfolio/summary'),
  positions: () => http.get('/portfolio/positions'),

  // ---------- recommendations ----------
  recommendations: () => http.get('/recommendations/latest'),
  analyze: (symbol, ctx) => http.post(`/recommendations/analyze/${symbol}`, { portfolio_context: ctx }),

  // ---------- orders ----------
  liveOrders: (params = {}) => http.get('/orders/live', { params }),
  placeOrder: (body) => http.post('/orders/live', body),
  cancelOrder: (id) => http.delete(`/orders/live/${id}`),
  getOrder: (id) => http.get(`/orders/live/${id}`),
  orderFills: (id) => http.get(`/orders/live/${id}/fills`),
  // legacy alias used by some views
  orders: (params = {}) => http.get('/orders/live', { params }),

  // ---------- risk ----------
  riskRules: () => http.get('/risk/rules'),
  riskEvents: (params = {}) => http.get('/risk/events', { params }),

  // ---------- news ----------
  newsArticles: (params = {}) => http.get('/news/articles', { params }),
  newsEvents: (params = {}) => http.get('/news/events', { params }),

  // ---------- signals ----------
  signals: (params = {}) => http.get('/signals', { params }),

  // ---------- admin ----------
  auditLogs: (params = {}) => http.get('/admin/audit-logs', { params }),

  // ---------- advisor ----------
  advisor: (watchlist) => http.get('/advisor/recommendations', {
    params: watchlist ? { watchlist: watchlist.join(',') } : {},
    timeout: 60000,
  }),

  // ---------- llm config ----------
  llmConfigGet: () => http.get('/llm/config'),
  llmConfigSet: (payload) => http.post('/llm/config', payload),
  llmConfigReset: () => http.delete('/llm/config'),
  llmTest: (level = 'quick') => http.post('/llm/test', null, { params: { level }, timeout: 120000 }),

  // ---------- agents ----------
  agentSkills: () => http.get('/agents/skills'),
  agentMemory: (params = {}) => http.get('/agents/memory', { params }),
  agentRunScout: () => http.post('/agents/scout/run', null, { timeout: 60000 }),
  agentRunGuardian: () => http.post('/agents/guardian/run', null, { timeout: 60000 }),
  agentRunResearch: (symbol) => http.post(`/agents/research/${symbol}`, null, { timeout: 60000 }),
  agentDailyBrief: () => http.post('/agents/daily-brief', null, { timeout: 90000 }),

  // ---------- scanner / picks ----------
  scannerLatest: () => http.get('/scanner/top-picks'),
  scannerFresh: (fresh = true, top_n = 10) =>
    http.get('/scanner/top-picks', { params: { fresh, top_n }, timeout: 60000 }),
  monitorLatest: () => http.get('/scanner/sell-warnings'),
  monitorFresh: () => http.get('/scanner/sell-warnings', { params: { fresh: true } }),

  // ---------- watchlist (自选股) ----------
  watchlistList: () => http.get('/watchlist/'),
  watchlistAdd: (symbol, note = '') => http.post('/watchlist/', { symbol, note }),
  watchlistRemove: (symbol) => http.delete(`/watchlist/${symbol}`),
  watchlistReorder: (symbols) => http.put('/watchlist/reorder', { symbols }),

  // ---------- system status / metrics ----------
  metricsJson: () => http.get('/metrics'),
  metricsProm: () => http.get('/metrics/prom', { responseType: 'text' }),
  wsStatus: () => http.get('/ws/status'),

  // ---------- notify ----------
  notifyStatus: () => http.get('/notify/status'),
  notifyTest: (payload) => http.post('/notify/test', payload),

  // ---------- research tracing ----------
  researchFactors: (symbol, params = {}) =>
    http.get(`/research/factors/${symbol}`, { params }),
  researchRuns: (params = {}) => http.get('/research/runs', { params }),

  // ---------- backtest ----------
  backtestRun: (body) => http.post('/backtest/run', body, { timeout: 120000 }),
  backtestWalkForward: (body) => http.post('/backtest/walk-forward', body, { timeout: 180000 }),

  // ---------- portfolio rebalance ----------
  portfolioRebalance: (body) => http.post('/portfolio/rebalance', body, { timeout: 30000 }),
}

/**
 * Open a WebSocket connection to a backend topic.
 * @param {string} topic   one of: 'quotes' | 'alerts' | 'advisor'
 * @param {(msg: any) => void} onMessage  receives parsed JSON payloads
 * @returns {() => void}  call to close the socket
 */
export function openStream(topic, onMessage) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const url = `${proto}://${location.host}/api/v1/ws/${topic}`
  let ws = null
  let closed = false
  let retry = 1000

  const connect = () => {
    ws = new WebSocket(url)
    ws.onmessage = (e) => {
      try { onMessage(JSON.parse(e.data)) } catch (_) {}
    }
    ws.onopen = () => { retry = 1000 }
    ws.onclose = () => {
      if (closed) return
      setTimeout(connect, retry)
      retry = Math.min(retry * 2, 15000)
    }
    ws.onerror = () => ws?.close()
  }

  connect()
  return () => { closed = true; ws?.close() }
}

// Backwards-compat alias used by LiveTicker
export const openQuoteStream = (onMessage) => openStream('quotes', onMessage)
