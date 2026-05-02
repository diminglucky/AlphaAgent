<template>
  <div>
    <el-card shadow="never" style="border-radius:8px; margin-bottom:20px">
      <el-form inline>
        <el-form-item label="操作类型">
          <el-select v-model="actionFilter" clearable placeholder="全部" style="width:180px" @change="load">
            <el-option v-for="a in ACTIONS" :key="a.value" :label="a.label" :value="a.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="操作人">
          <el-input v-model="actorFilter" placeholder="如 system" clearable style="width:130px" @change="load" />
        </el-form-item>
        <el-form-item>
          <el-button @click="load">查询</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" style="border-radius:8px">
      <template #header>
        <span style="font-weight:600">📜 审计日志</span>
        <span style="float:right; font-size:13px; color:#8c8c8c">共 {{ logs.length }} 条</span>
      </template>
      <el-table :data="logs" v-loading="loading" size="small" stripe>
        <el-table-column prop="created_at" label="时间" width="170" />
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <el-tag :type="actionTagType(row.action)" size="small">{{ row.action }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="actor" label="操作人" width="100" />
        <el-table-column prop="resource_type" label="资源类型" width="110" />
        <el-table-column prop="resource_id" label="资源ID" width="200" show-overflow-tooltip />
        <el-table-column label="详情" show-overflow-tooltip>
          <template #default="{ row }">{{ formatDetails(row.details) }}</template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && logs.length === 0" description="暂无审计日志" :image-size="80" />
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api.js'

const ACTIONS = [
  { value: 'ORDER_SUBMITTED', label: '订单提交' },
  { value: 'ORDER_CANCELLED', label: '订单撤销' },
  { value: 'ORDER_FILLED', label: '订单成交' },
  { value: 'RISK_RULE_CHANGED', label: '风控规则变更' },
  { value: 'RISK_EVENT_LOGGED', label: '风控事件记录' },
  { value: 'NEWS_INGESTED', label: '新闻摄入' },
  { value: 'SIGNAL_SAVED', label: '信号保存' },
]

const logs = ref([])
const loading = ref(false)
const actionFilter = ref('')
const actorFilter = ref('')

const actionTagType = a => {
  if (a?.startsWith('ORDER')) return 'primary'
  if (a?.startsWith('RISK')) return 'danger'
  if (a?.startsWith('NEWS')) return 'warning'
  if (a?.startsWith('SIGNAL')) return 'success'
  return 'info'
}

const formatDetails = (d) => {
  if (!d) return '–'
  if (typeof d === 'string') return d
  try { return JSON.stringify(d) } catch { return String(d) }
}

const load = async () => {
  loading.value = true
  try {
    const params = { limit: 100 }
    if (actionFilter.value) params.action = actionFilter.value
    if (actorFilter.value) params.actor = actorFilter.value
    const data = await api.auditLogs(params)
    logs.value = Array.isArray(data) ? data : (data.logs ?? [])
  } catch {
    logs.value = []
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>
