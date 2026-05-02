<template>
  <el-container v-if="isSimpleMode" style="height: 100vh; background:#f5f7fa">
    <el-container>
      <el-header style="background:#fff; border-bottom:1px solid #f0f0f0; display:flex; align-items:center; justify-content:space-between; padding:0 24px">
        <div style="display:flex; align-items:center; gap:12px">
          <span style="font-size:24px">📈</span>
          <div>
            <div style="font-size:18px; font-weight:700; color:#111">买 / 卖决策器</div>
            <div style="font-size:12px; color:#999">只保留两个核心动作：找买点、找卖点</div>
          </div>
        </div>
        <div style="display:flex; align-items:center; gap:10px">
          <el-badge :value="unreadAlertCount" :hidden="unreadAlertCount === 0" :max="99">
            <el-button :icon="Bell" circle size="small" @click="openAlerts" />
          </el-badge>
          <el-tag :type="apiOk ? 'success' : 'danger'" size="small">
            {{ apiOk ? 'API 正常' : 'API 异常' }}
          </el-tag>
          <el-button size="small" @click="go('/portfolio')">持仓</el-button>
          <el-button size="small" @click="go('/orders')">订单</el-button>
          <el-button size="small" @click="go('/settings/llm')">LLM 设置</el-button>
          <el-dropdown @command="go">
            <el-button size="small">更多</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="/picks">今日推荐</el-dropdown-item>
                <el-dropdown-item command="/agents">Agent 控制台</el-dropdown-item>
                <el-dropdown-item command="/market">行情</el-dropdown-item>
                <el-dropdown-item command="/analysis">智能分析</el-dropdown-item>
                <el-dropdown-item command="/risk">风控</el-dropdown-item>
                <el-dropdown-item command="/news">新闻</el-dropdown-item>
                <el-dropdown-item command="/system">系统状态</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-drawer v-model="alertDrawerOpen" title="🔔 实时告警" size="420px">
        <el-empty v-if="!alerts.length" description="暂无告警" />
        <div v-else>
          <el-card
            v-for="a in alerts"
            :key="a.id"
            shadow="never"
            style="margin-bottom:10px"
          >
            <div style="display:flex; justify-content:space-between; align-items:center">
              <strong>{{ a.title }}</strong>
              <el-tag :type="a.level === 'error' ? 'danger' : a.level === 'success' ? 'success' : 'warning'" size="small">
                {{ a.alert_type }}
              </el-tag>
            </div>
            <p style="color:#555; font-size:13px; margin-top:6px">{{ a.body }}</p>
            <p style="color:#aaa; font-size:11px; margin-top:6px">
              {{ new Date(a.timestamp).toLocaleString('zh-CN') }}
            </p>
          </el-card>
        </div>
      </el-drawer>

      <el-main style="padding:20px; overflow-y:auto; max-width:1400px; width:100%; margin:0 auto">
        <router-view />
      </el-main>
    </el-container>
  </el-container>

  <el-container v-else style="height: 100vh">
    <el-aside width="220px" style="background:#001529; overflow:hidden">
      <div class="logo">
        <span class="logo-icon">📈</span>
        <span class="logo-text">量化平台</span>
      </div>
      <el-menu
        :default-active="activeMenu"
        background-color="#001529"
        text-color="#ffffffa0"
        active-text-color="#ffffff"
        router
      >
        <el-menu-item index="/simple"><el-icon><Lightning /></el-icon>买入 / 卖出</el-menu-item>
        <el-menu-item index="/portfolio"><el-icon><Wallet /></el-icon>当前持仓</el-menu-item>
        <el-menu-item index="/orders"><el-icon><List /></el-icon>订单</el-menu-item>
        <el-menu-item index="/settings/llm"><el-icon><Setting /></el-icon>LLM 设置</el-menu-item>
        <el-sub-menu index="advanced">
          <template #title>
            <el-icon><Cpu /></el-icon>
            <span>高级功能</span>
          </template>
          <el-menu-item index="/picks"><el-icon><MagicStick /></el-icon>今日推荐</el-menu-item>
          <el-menu-item index="/agents"><el-icon><Cpu /></el-icon>Agent 控制台</el-menu-item>
          <el-menu-item index="/dashboard"><el-icon><HomeFilled /></el-icon>总览</el-menu-item>
          <el-menu-item index="/market"><el-icon><TrendCharts /></el-icon>行情</el-menu-item>
          <el-menu-item index="/analysis"><el-icon><MagicStick /></el-icon>智能分析</el-menu-item>
          <el-menu-item index="/watchlist"><el-icon><Star /></el-icon>自选股</el-menu-item>
          <el-menu-item index="/risk"><el-icon><Warning /></el-icon>风控</el-menu-item>
          <el-menu-item index="/news"><el-icon><ChatDotRound /></el-icon>新闻</el-menu-item>
          <el-menu-item index="/audit"><el-icon><Document /></el-icon>审计</el-menu-item>
          <el-menu-item index="/backtest"><el-icon><DataLine /></el-icon>策略回测</el-menu-item>
          <el-menu-item index="/reports"><el-icon><Document /></el-icon>日报</el-menu-item>
          <el-menu-item index="/system"><el-icon><Monitor /></el-icon>系统状态</el-menu-item>
        </el-sub-menu>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header style="background:#fff; border-bottom:1px solid #f0f0f0; display:flex; align-items:center; justify-content:space-between; padding:0 24px">
        <span style="font-size:16px; font-weight:600; color:#333">{{ pageTitle }}</span>
        <div style="display:flex; align-items:center; gap:16px">
          <el-badge :value="unreadAlertCount" :hidden="unreadAlertCount === 0" :max="99">
            <el-button :icon="Bell" circle size="small" @click="openAlerts" />
          </el-badge>
          <el-tag :type="connected ? 'success' : 'warning'" size="small">
            {{ connected ? '● 实时连接中' : '○ 等待实时数据' }}
          </el-tag>
          <el-tag :type="apiOk ? 'success' : 'danger'" size="small">
            {{ apiOk ? '● API 运行中' : '● API 离线' }}
          </el-tag>
          <span style="color:#999; font-size:13px">{{ currentTime }}</span>
        </div>
      </el-header>

      <el-drawer v-model="alertDrawerOpen" title="🔔 实时告警" size="420px">
        <el-empty v-if="!alerts.length" description="暂无告警" />
        <div v-else>
          <el-card
            v-for="a in alerts"
            :key="a.id"
            shadow="never"
            style="margin-bottom:10px"
          >
            <div style="display:flex; justify-content:space-between; align-items:center">
              <strong>{{ a.title }}</strong>
              <el-tag :type="a.level === 'error' ? 'danger' : a.level === 'success' ? 'success' : 'warning'" size="small">
                {{ a.alert_type }}
              </el-tag>
            </div>
            <p style="color:#555; font-size:13px; margin-top:6px">{{ a.body }}</p>
            <p style="color:#aaa; font-size:11px; margin-top:6px">
              {{ new Date(a.timestamp).toLocaleString('zh-CN') }}
            </p>
          </el-card>
        </div>
      </el-drawer>

      <el-main style="background:#f5f7fa; padding:24px; overflow-y:auto">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from './api.js'
import { Bell } from '@element-plus/icons-vue'
import {
  bootstrapRealtime, alerts, unreadAlertCount, markAlertsRead,
} from './realtimeStore.js'

const route = useRoute()
const router = useRouter()
const apiOk = ref(false)
const currentTime = ref('')
const alertDrawerOpen = ref(false)

const activeMenu = computed(() => route.path)
const pageTitle = computed(() => route.meta?.title || 'A股量化平台')
const isSimpleMode = computed(() => route.path === '/simple')

let timer = null

const updateTime = () => {
  currentTime.value = new Date().toLocaleTimeString('zh-CN')
}

const checkApi = async () => {
  try {
    await api.health()
    apiOk.value = true
  } catch {
    apiOk.value = false
  }
}

const openAlerts = () => {
  alertDrawerOpen.value = true
  markAlertsRead()
}

const go = (path) => {
  if (path) router.push(path)
}

onMounted(() => {
  updateTime()
  checkApi()
  bootstrapRealtime()
  timer = setInterval(() => {
    updateTime()
    checkApi()
  }, 10000)
})

onUnmounted(() => clearInterval(timer))
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif; }

.logo {
  height: 64px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 20px;
  border-bottom: 1px solid #ffffff10;
}
.logo-icon { font-size: 24px; }
.logo-text { color: #fff; font-size: 16px; font-weight: 700; letter-spacing: 1px; }

.el-menu { border-right: none; }
.el-menu-item { height: 50px; line-height: 50px; }
</style>
