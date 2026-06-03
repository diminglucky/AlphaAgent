import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/advisor' },
  {
    path: '/advisor',
    component: () => import('../views/RealtimeAdvisor.vue'),
    meta: { title: '实时推荐' },
  },
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
    path: '/evolution',
    component: () => import('../views/Evolution.vue'),
    meta: { title: '模型进化' },
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
    path: '/trading',
    component: () => import('../views/Trading.vue'),
    meta: { title: '交易' },
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
