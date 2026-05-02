<template>
  <div>
    <el-row :gutter="16">
      <!-- Risk rules -->
      <el-col :span="14">
        <el-card shadow="never" style="border-radius:8px; margin-bottom:20px">
          <template #header><span style="font-weight:600">🛡 风控规则</span></template>
          <el-table :data="rules" v-loading="loadingRules" size="small" stripe>
            <el-table-column prop="rule_id" label="规则ID" width="200" />
            <el-table-column prop="rule_type" label="类型" width="160" />
            <el-table-column prop="scope" label="范围" width="100" />
            <el-table-column prop="description" label="描述" show-overflow-tooltip />
            <el-table-column label="阈值" width="100">
              <template #default="{ row }">{{ row.threshold }}</template>
            </el-table-column>
            <el-table-column label="违规动作" width="100">
              <template #default="{ row }">
                <el-tag :type="row.action_on_breach === 'BLOCK' ? 'danger' : 'warning'" size="small">
                  {{ row.action_on_breach }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="80">
              <template #default="{ row }">
                <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
                  {{ row.enabled ? '启用' : '停用' }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <!-- Risk events -->
        <el-card shadow="never" style="border-radius:8px">
          <template #header>
            <span style="font-weight:600">⚠️ 风控事件</span>
            <el-select v-model="eventFilter" size="small" style="float:right; width:100px" @change="loadEvents">
              <el-option value="" label="全部" />
              <el-option value="BLOCK" label="拦截" />
              <el-option value="WARN" label="警告" />
              <el-option value="PASS" label="通过" />
            </el-select>
          </template>
          <el-table :data="events" v-loading="loadingEvents" size="small" stripe>
            <el-table-column prop="symbol" label="标的" width="110" />
            <el-table-column prop="rule_name" label="触发规则" />
            <el-table-column label="决策" width="80">
              <template #default="{ row }">
                <el-tag :type="decisionType(row.decision)" size="small">{{ row.decision }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="triggered_value" label="触发值" width="90" />
            <el-table-column prop="created_at" label="时间" width="160" show-overflow-tooltip />
          </el-table>
          <el-empty v-if="!loadingEvents && events.length === 0" description="暂无风控事件" :image-size="60" />
        </el-card>
      </el-col>

      <!-- Summary -->
      <el-col :span="10">
        <el-card shadow="never" style="border-radius:8px; margin-bottom:20px">
          <template #header><span style="font-weight:600">📊 事件统计</span></template>
          <el-statistic
            v-for="s in eventStats"
            :key="s.label"
            :title="s.label"
            :value="s.value"
            style="margin-bottom:16px"
          >
            <template #suffix>
              <el-tag :type="s.type" size="small" style="margin-left:8px">{{ s.tag }}</el-tag>
            </template>
          </el-statistic>
        </el-card>

        <el-card shadow="never" style="border-radius:8px">
          <template #header><span style="font-weight:600">ℹ️ 风控说明</span></template>
          <p style="font-size:13px; color:#555; line-height:2">
            风控引擎在每笔订单提交前自动检查所有启用的规则。
            <br>• <strong>BLOCK</strong> — 订单被拦截，无法执行
            <br>• <strong>WARN</strong> — 发出警告，订单可继续
            <br>• <strong>PASS</strong> — 规则通过，正常执行
          </p>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api.js'

const rules = ref([])
const events = ref([])
const loadingRules = ref(false)
const loadingEvents = ref(false)
const eventFilter = ref('')

const decisionType = d => ({ BLOCK: 'danger', WARN: 'warning', PASS: 'success' }[d] || 'info')

const eventStats = computed(() => {
  const total = events.value.length
  const blocked = events.value.filter(e => e.decision === 'BLOCK').length
  const warned = events.value.filter(e => e.decision === 'WARN').length
  return [
    { label: '总事件数', value: total, type: 'info', tag: '条' },
    { label: '拦截', value: blocked, type: 'danger', tag: '次' },
    { label: '警告', value: warned, type: 'warning', tag: '次' },
    { label: '通过', value: total - blocked - warned, type: 'success', tag: '次' },
  ]
})

const loadRules = async () => {
  loadingRules.value = true
  try {
    const data = await api.riskRules()
    rules.value = Array.isArray(data) ? data : (data.rules ?? [])
  } finally {
    loadingRules.value = false
  }
}

const loadEvents = async () => {
  loadingEvents.value = true
  try {
    const params = { limit: 50 }
    if (eventFilter.value) params.decision = eventFilter.value
    const data = await api.riskEvents(params)
    events.value = Array.isArray(data) ? data : (data.events ?? [])
  } finally {
    loadingEvents.value = false
  }
}

onMounted(() => {
  loadRules()
  loadEvents()
})
</script>
