import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/overview' },
  {
    path: '/overview',
    component: () => import('../views/Overview.vue'),
    meta: { title: '市场总览' },
  },
  {
    path: '/market',
    component: () => import('../views/Market.vue'),
    meta: { title: '行情' },
  },
  {
    path: '/scanner',
    component: () => import('../views/Scanner.vue'),
    meta: { title: '潜力扫描' },
  },
  {
    path: '/agent',
    component: () => import('../views/Agent.vue'),
    meta: { title: 'Agent 分析' },
  },
  {
    path: '/alerts',
    component: () => import('../views/Alerts.vue'),
    meta: { title: '提醒' },
  },
  {
    path: '/positions',
    component: () => import('../views/Positions.vue'),
    meta: { title: '持仓' },
  },
  {
    path: '/settings',
    component: () => import('../views/Settings.vue'),
    meta: { title: '设置' },
  },
]

export default createRouter({
  history: createWebHashHistory(),
  routes,
})
