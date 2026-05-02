import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/simple' },
  { path: '/simple', component: () => import('../views/Simple.vue'), meta: { title: '买入 / 卖出' } },
  { path: '/picks', component: () => import('../views/Picks.vue'), meta: { title: '今日推荐' } },
  { path: '/agents', component: () => import('../views/Agents.vue'), meta: { title: 'Agent 控制台' } },
  { path: '/settings/llm', component: () => import('../views/LLMSettings.vue'), meta: { title: 'LLM 设置' } },
  { path: '/dashboard', component: () => import('../views/Dashboard.vue'), meta: { title: '总览' } },
  { path: '/market', component: () => import('../views/Market.vue'), meta: { title: '行情' } },
  { path: '/portfolio', component: () => import('../views/Portfolio.vue'), meta: { title: '持仓' } },
  { path: '/analysis', component: () => import('../views/Analysis.vue'), meta: { title: '智能分析' } },
  { path: '/watchlist', component: () => import('../views/Watchlist.vue'), meta: { title: '自选股' } },
  { path: '/orders', component: () => import('../views/Orders.vue'), meta: { title: '订单' } },
  { path: '/risk', component: () => import('../views/Risk.vue'), meta: { title: '风控' } },
  { path: '/news', component: () => import('../views/News.vue'), meta: { title: '新闻' } },
  { path: '/audit', component: () => import('../views/Audit.vue'), meta: { title: '审计' } },
  { path: '/backtest', component: () => import('../views/Backtest.vue'), meta: { title: '策略回测' } },
  { path: '/reports', component: () => import('../views/Reports.vue'), meta: { title: '日报' } },
  { path: '/system', component: () => import('../views/SystemStatus.vue'), meta: { title: '系统状态' } },
]

export default createRouter({
  history: createWebHashHistory(),
  routes,
})
