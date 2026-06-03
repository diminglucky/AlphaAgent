import axios from 'axios'

const API_KEY_STORAGE = 'alphaagent:api_key'

export const http = axios.create({
  baseURL: '/api/v1',
  timeout: 60000,
})

http.interceptors.request.use(config => {
  const key = localStorage.getItem(API_KEY_STORAGE)
  if (key) {
    config.headers = config.headers || {}
    config.headers['X-Api-Key'] = key
  }
  return config
})

http.interceptors.response.use(
  res => res.data,
  err => {
    const msg = err.response?.data?.detail || err.message || '请求失败'
    return Promise.reject(new Error(msg))
  }
)

export function getApiKey() {
  return localStorage.getItem(API_KEY_STORAGE) || ''
}

export function setApiKey(key) {
  const value = String(key || '').trim()
  if (value) localStorage.setItem(API_KEY_STORAGE, value)
  else localStorage.removeItem(API_KEY_STORAGE)
}

export const api = {
  // 行情
  quote: (symbol) => http.get(`/market/quote/${symbol}`),
  quotes: (symbols) => http.get('/market/quotes', { params: { symbols: symbols.join(',') } }),
  kline: (symbol, period = 'daily', count = 120) =>
    http.get(`/market/kline/${symbol}`, { params: { period, count } }),
  search: (keyword) => http.get('/market/search', { params: { keyword } }),
  news: (symbol, count = 10) => http.get(`/market/news/${symbol}`, { params: { count } }),
  hot: (top_n = 500) => http.get('/market/hot', { params: { top_n } }),
  cacheStatus: () => http.get('/market/cache-status'),

  // 自选股
  watchlist: () => http.get('/watchlist/'),
  watchlistWithQuotes: () => http.get('/watchlist/with-quotes'),
  watchlistAdd: (symbol, name = '', note = '') => http.post('/watchlist/', { symbol, name, note }),
  watchlistRemove: (symbol) => http.delete(`/watchlist/${symbol}`),

  // Agent 分析
  analyze: (symbol) => http.post(`/agent/analyze/${symbol}`, null, { timeout: 300000 }),  // 5分钟
  scan: () => http.post('/agent/scan', null, { timeout: 600000 }),  // 10分钟
  analysisCache: () => http.get('/agent/cache'),
  analysisCacheOne: (symbol) => http.get(`/agent/cache/${symbol}`),

  // 提醒
  alerts: (triggered) => http.get('/alerts/', { params: triggered !== undefined ? { triggered } : {} }),
  createAlert: (data) => http.post('/alerts/', data),
  deleteAlert: (id) => http.delete(`/alerts/${id}`),

  // 持仓
  positions: () => http.get('/positions/'),
  upsertPosition: (data) => http.post('/positions/', data),
  deletePosition: (symbol) => http.delete(`/positions/${symbol}`),

  // 交易闭环
  tradingAccount: () => http.get('/trading/account'),
  tradingPositions: () => http.get('/trading/positions'),
  tradingOrders: (limit = 100) => http.get('/trading/orders', { params: { limit } }),
  tradingFills: (limit = 100) => http.get('/trading/fills', { params: { limit } }),
  tradingSync: (limit = 200) => http.post('/trading/sync', null, { params: { limit }, timeout: 120000 }),
  tradingPreview: (data) => http.post('/trading/preview', data),
  tradingPlaceOrder: (data) => http.post('/trading/orders', data),
  tradingCancelOrder: (orderId) => http.post(`/trading/orders/${orderId}/cancel`),

  // 系统
  health: () => http.get('/health'),
  wsStatus: () => http.get('/ws/status'),

  // LLM 配置（运行时热更新，无需重启）
  llmConfig: () => http.get('/llm/config'),
  llmConfigSet: (data) => http.post('/llm/config', data),
  llmConfigReset: () => http.delete('/llm/config'),
  llmTest: (level = 'quick') => http.post('/llm/test', null, { params: { level }, timeout: 120000 }),
  llmUsage: (params = {}) => http.get('/llm/usage', { params }),

  // 大盘扫描器（潜力股）
  scannerScan: (data = {}) => http.post('/scanner/scan', {
    top_n: 30, min_score: 50, candidate_pool: 120, use_cache: true,
    required_strategies: null,
    ...data,
  }, { timeout: 600000 }),
  scannerStrategies: () => http.get('/scanner/strategies'),
  scannerStatus: () => http.get('/scanner/status'),
  scannerClearCache: () => http.delete('/scanner/cache'),

  // 模型进化
  evolutionSummary: () => http.get('/evolution/summary'),
  evolutionPredictions: (params = {}) => http.get('/evolution/predictions', { params }),
  evolutionModels: () => http.get('/evolution/models'),
  evolutionScanRuns: (params = {}) => http.get('/evolution/scan-runs', { params }),
  evolutionCompare: (params = {}) => http.get('/evolution/compare', { params }),
  evolutionValidate: (data = {}) => http.post('/evolution/validate', data, { timeout: 300000 }),
  evolutionEvolve: (data = {}) => http.post('/evolution/evolve', data),
  evolutionAutoCycle: () => http.post('/evolution/auto-cycle'),
}

// WebSocket 工具
export function openStream(topic, onMessage) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const url = `${proto}://${location.host}/api/v1/ws/${topic}`
  let ws = null
  let closed = false
  let retryMs = 2000

  const connect = () => {
    ws = new WebSocket(url)
    ws.onopen = () => { retryMs = 2000 }
    ws.onmessage = (e) => {
      try { onMessage(JSON.parse(e.data)) } catch (_) {}
    }
    ws.onclose = () => {
      if (closed) return
      setTimeout(connect, retryMs)
      retryMs = Math.min(retryMs * 1.5, 30000)
    }
    ws.onerror = () => ws?.close()
  }

  connect()
  return () => { closed = true; ws?.close() }
}
