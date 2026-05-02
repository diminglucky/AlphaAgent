<template>
  <div class="page">
    <div class="page-header">
      <h2>系统状态</h2>
      <div>
        <el-button @click="refresh" :loading="loading">刷新</el-button>
        <el-button type="primary" @click="auto = !auto">
          {{ auto ? '⏸ 暂停自动刷新' : '▶ 自动刷新 (15s)' }}
        </el-button>
      </div>
    </div>

    <!-- Background loops -->
    <el-card v-if="loops" shadow="never" class="card">
      <template #header><b>后台循环</b></template>
      <el-row :gutter="20">
        <el-col :span="6" v-for="k in loopKeys" :key="k">
          <el-statistic :title="loopLabels[k]" :value="loops[k] ? '运行中' : '已停止'">
            <template #suffix>
              <el-tag :type="loops[k] ? 'success' : 'danger'" size="small" effect="plain">
                {{ loops[k] ? '✓' : '✗' }}
              </el-tag>
            </template>
          </el-statistic>
        </el-col>
      </el-row>
    </el-card>

    <!-- Counters -->
    <el-card v-if="metrics" shadow="never" class="card">
      <template #header><b>核心计数器</b></template>
      <el-row :gutter="20">
        <el-col :span="4" v-for="(v, k) in metrics.counters" :key="k">
          <el-statistic :title="counterLabels[k] || k" :value="v" />
        </el-col>
      </el-row>
    </el-card>

    <!-- WebSocket subscribers -->
    <el-card v-if="metrics" shadow="never" class="card">
      <template #header><b>WebSocket 订阅</b></template>
      <el-row :gutter="20">
        <el-col :span="6"><el-statistic title="行情订阅" :value="metrics.websocket.quotes_subscribers" /></el-col>
        <el-col :span="6"><el-statistic title="告警订阅" :value="metrics.websocket.alerts_subscribers" /></el-col>
        <el-col :span="6"><el-statistic title="顾问订阅" :value="metrics.websocket.advisor_subscribers" /></el-col>
      </el-row>
    </el-card>

    <!-- Cache stats -->
    <el-card v-if="metrics" shadow="never" class="card">
      <template #header><b>缓存命中</b></template>
      <div v-if="metrics.kv_cache">
        <p><b>KV cache:</b> backend = <el-tag>{{ metrics.kv_cache.backend }}</el-tag>,
          命中率 = <b>{{ (metrics.kv_cache.hit_rate * 100).toFixed(1) }}%</b>
          ({{ metrics.kv_cache.hits }} hits / {{ metrics.kv_cache.misses }} misses)
        </p>
      </div>
      <el-table v-if="marketCacheRows.length" :data="marketCacheRows" size="small" stripe>
        <el-table-column prop="fn" label="函数" />
        <el-table-column prop="size" label="缓存大小" width="120" />
        <el-table-column prop="hits" label="命中" width="100" />
        <el-table-column prop="misses" label="未命中" width="100" />
        <el-table-column label="命中率" width="120">
          <template #default="{ row }">{{ (row.hit_rate * 100).toFixed(1) }}%</template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Notify status -->
    <el-card v-if="notify" shadow="never" class="card">
      <template #header><b>通知通道</b></template>
      <el-row :gutter="20">
        <el-col :span="12">
          <el-card shadow="never" body-style="padding: 12px;">
            <p><b>Webhook:</b>
              <el-tag :type="notify.webhook.enabled ? 'success' : 'info'">
                {{ notify.webhook.enabled ? '已启用' : '未配置' }}
              </el-tag>
            </p>
            <p>格式: {{ notify.webhook.format }}</p>
          </el-card>
        </el-col>
        <el-col :span="12">
          <el-card shadow="never" body-style="padding: 12px;">
            <p><b>Email (SMTP):</b>
              <el-tag :type="notify.email.enabled ? 'success' : 'info'">
                {{ notify.email.enabled ? '已启用' : '未配置' }}
              </el-tag>
            </p>
            <p v-if="notify.email.smtp_host">Host: {{ notify.email.smtp_host }}:{{ notify.email.smtp_port }}</p>
            <p v-if="notify.email.to">To: {{ notify.email.to }}</p>
          </el-card>
        </el-col>
      </el-row>
      <div style="margin-top: 12px;">
        <el-button @click="testNotify" :loading="notifying">发送测试通知</el-button>
        <span v-if="notifyResult" style="margin-left: 12px;">
          <el-tag v-for="(ok, ch) in notifyResult.results" :key="ch"
                  :type="ok ? 'success' : 'danger'" style="margin-right: 6px;">
            {{ ch }}: {{ ok ? '成功' : '失败' }}
          </el-tag>
        </span>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api.js'

const loading = ref(false)
const auto = ref(false)
const metrics = ref(null)
const loops = ref(null)
const notify = ref(null)
const notifyResult = ref(null)
const notifying = ref(false)
let timer = null

const loopKeys = ['feed_running', 'advisor_running', 'scanner_running', 'monitor_running']
const loopLabels = {
  feed_running: '行情推送',
  advisor_running: '顾问循环',
  scanner_running: '市场扫描',
  monitor_running: '持仓监控',
}
const counterLabels = {
  orders_total: '订单总数',
  orders_pending: '挂单',
  orders_filled: '已成交',
  orders_cancelled: '已撤销',
  signals_total: '信号',
  recommendations_total: '推荐',
  risk_events_total: '风控事件',
  risk_events_blocked: '已拦截',
  audit_logs_total: '审计日志',
}

const marketCacheRows = computed(() => {
  if (!metrics.value || !metrics.value.market_cache) return []
  return Object.entries(metrics.value.market_cache).map(([fn, st]) => ({ fn, ...st }))
})

const refresh = async () => {
  loading.value = true
  try {
    const [m, ws, n] = await Promise.all([
      api.metricsJson().catch(() => ({ data: null })),
      api.wsStatus().catch(() => ({ data: null })),
      api.notifyStatus().catch(() => ({ data: null })),
    ])
    metrics.value = m.data
    loops.value = ws.data
    notify.value = n.data
  } finally {
    loading.value = false
  }
}

const testNotify = async () => {
  notifying.value = true
  notifyResult.value = null
  try {
    const r = await api.notifyTest({ title: '[Quant] UI 测试通知', body: 'Hello from System Status', level: 'info' })
    notifyResult.value = r.data
    if (r.data.n_succeeded > 0) {
      ElMessage.success(`${r.data.n_succeeded} / ${r.data.n_channels_attempted} 个通道发送成功`)
    } else if (r.data.n_channels_attempted === 0) {
      ElMessage.info('无配置的通知通道')
    } else {
      ElMessage.error('全部通道发送失败')
    }
  } catch (e) {
    ElMessage.error('测试失败: ' + (e?.response?.data?.detail || e.message))
  } finally {
    notifying.value = false
  }
}

const startTimer = () => {
  if (timer) clearInterval(timer)
  timer = setInterval(() => { if (auto.value) refresh() }, 15000)
}

onMounted(() => { refresh(); startTimer() })
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<style scoped>
.page { padding: 16px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.card { margin-bottom: 16px; }
</style>
