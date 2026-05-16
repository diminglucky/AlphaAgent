import axios from 'axios'

export const http = axios.create({
  baseURL: '/api/v1',
  timeout: 60000,
})

http.interceptors.response.use(
  res => res.data,
  err => {
    const msg = err.response?.data?.detail || err.message || '请求失败'
    return Promise.reject(new Error(msg))
  }
)

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

  // 系统
  health: () => http.get('/health'),
  wsStatus: () => http.get('/ws/status'),

  // LLM 配置（运行时热更新，无需重启）
  llmConfig: () => http.get('/llm/config'),
  llmConfigSet: (data) => http.post('/llm/config', data),
  llmConfigReset: () => http.delete('/llm/config'),
  llmTest: (level = 'quick') => http.post('/llm/test', null, { params: { level }, timeout: 120000 }),
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
