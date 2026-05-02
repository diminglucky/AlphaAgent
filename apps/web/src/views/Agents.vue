<template>
  <div>
    <el-row :gutter="16" style="margin-bottom:16px">
      <el-col :span="6">
        <el-card shadow="never">
          <div style="font-size:12px; color:#999">已注册技能</div>
          <div style="font-size:32px; font-weight:600">{{ skills.count }}</div>
          <div style="font-size:12px; color:#666">{{ (skills.categories || []).join(' · ') }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never">
          <div style="font-size:12px; color:#999">运行模式</div>
          <div style="font-size:18px; font-weight:600; color:#1890ff">
            {{ llmAvailable ? '🧠 LLM 自主推理' : '⚙️ Fallback 确定性' }}
          </div>
          <div style="font-size:12px; color:#999; margin-top:4px">
            {{ llmAvailable ? '配置真模型，Agent 多步思考' : '设 QUANT_LLM_PROVIDER 启用 LLM' }}
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never">
          <div style="font-size:12px; color:#999">决策记忆</div>
          <div style="font-size:32px; font-weight:600">{{ memory.summary?.n_entries || 0 }}</div>
          <div style="font-size:12px; color:#666">条历史</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never">
          <div style="font-size:12px; color:#999">活跃 Agent</div>
          <div style="font-size:32px; font-weight:600">{{ (memory.summary?.agents || []).length }}</div>
          <div style="font-size:12px; color:#666">{{ (memory.summary?.agents || []).join(', ') }}</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Trigger panel -->
    <el-card shadow="never" style="margin-bottom:16px">
      <template #header><span style="font-weight:600">🚀 触发 Agent 任务</span></template>
      <el-space wrap>
        <el-button type="primary" @click="runScout" :loading="loading.scout">🔍 MarketScout 扫市场</el-button>
        <el-button type="primary" @click="runGuardian" :loading="loading.guardian">🛡️ Guardian 诊断持仓</el-button>
        <el-input v-model="researchSymbol" placeholder="输入代码如 002230.SZ" style="width:180px" />
        <el-button @click="runResearch" :loading="loading.research" :disabled="!researchSymbol">🔬 Research 深度研究</el-button>
        <el-button type="success" @click="runDailyBrief" :loading="loading.brief">📋 一键日报</el-button>
      </el-space>
    </el-card>

    <!-- Latest run trace -->
    <el-card v-if="lastRun" shadow="never" style="margin-bottom:16px">
      <template #header>
        <span style="font-weight:600">{{ lastRun.agent }}</span>
        <el-tag :type="lastRun.status==='success' ? 'success' : 'danger'" size="small" style="margin-left:8px">{{ lastRun.status }}</el-tag>
        <el-tag :type="lastRun.llm_powered ? 'primary' : 'info'" size="small" style="margin-left:4px">
          {{ lastRun.llm_powered ? 'LLM' : 'Fallback' }}
        </el-tag>
        <span style="float:right; font-size:12px; color:#999">
          {{ lastRun.tool_calls_made }} tool calls · {{ lastRun.duration_ms }} ms
        </span>
      </template>
      <div style="margin-bottom:12px; padding:8px; background:#f5f7fa; border-radius:4px">
        <span style="font-size:12px; color:#999">Goal:</span>
        <div style="font-size:13px">{{ lastRun.goal }}</div>
      </div>

      <h4 style="margin:8px 0">最终结论</h4>
      <pre style="background:#fafafa; padding:12px; border-radius:4px; font-size:12px; max-height:280px; overflow:auto">{{ JSON.stringify(lastRun.final_answer, null, 2) }}</pre>

      <el-divider />

      <h4 style="margin:8px 0">推理 Trace ({{ lastRun.trace.length }} 步)</h4>
      <el-timeline>
        <el-timeline-item
          v-for="(s, i) in lastRun.trace" :key="i"
          :type="traceColor(s.role)"
          :timestamp="formatTraceTitle(s)"
          placement="top"
        >
          <div style="font-size:12px; max-height:150px; overflow:auto;
                      background:#f9f9f9; padding:8px; border-radius:4px">
            <pre style="margin:0; white-space:pre-wrap; word-break:break-all">{{ JSON.stringify(s.content, null, 2) }}</pre>
          </div>
        </el-timeline-item>
      </el-timeline>
    </el-card>

    <!-- Memory + skills tabs -->
    <el-tabs v-model="activeTab">
      <el-tab-pane label="决策历史 (Memory)" name="memory">
        <el-table :data="memory.entries || []" size="small" stripe height="400">
          <el-table-column prop="timestamp" label="时间" width="170">
            <template #default="{ row }">{{ formatTime(row.timestamp) }}</template>
          </el-table-column>
          <el-table-column prop="agent" label="Agent" width="160" />
          <el-table-column prop="role" label="类型" width="120">
            <template #default="{ row }">
              <el-tag size="small">{{ row.role }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="内容" show-overflow-tooltip>
            <template #default="{ row }">
              <code style="font-size:11px">{{ JSON.stringify(row.content).slice(0, 200) }}</code>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="技能清单 (Skills)" name="skills">
        <el-table :data="skills.skills || []" size="small" stripe height="400">
          <el-table-column prop="name" label="名称" width="220">
            <template #default="{ row }"><code>{{ row.name }}</code></template>
          </el-table-column>
          <el-table-column prop="category" label="类别" width="110">
            <template #default="{ row }">
              <el-tag size="small" :type="catTag(row.category)">{{ row.category }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="description" label="描述" show-overflow-tooltip />
          <el-table-column label="参数" width="200">
            <template #default="{ row }">
              <span style="font-size:11px; color:#666">
                {{ Object.keys(row.parameters?.properties || {}).join(', ') || '-' }}
              </span>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api.js'

const skills = ref({ count: 0, categories: [], skills: [] })
const memory = ref({ summary: {}, entries: [] })
const lastRun = ref(null)
const loading = ref({ scout: false, guardian: false, research: false, brief: false })
const researchSymbol = ref('002230.SZ')
const activeTab = ref('memory')
const llmAvailable = ref(false)

const formatTime = (iso) => iso ? new Date(iso).toLocaleString('zh-CN', { hour12: false }) : '-'

const traceColor = (role) => ({
  thought: 'primary', tool_call: 'warning', tool_result: 'success', final: 'success',
}[role] || 'info')

const formatTraceTitle = (s) => {
  if (s.role === 'tool_call') return `🔧 调用 ${s.content?.name}`
  if (s.role === 'tool_result') return `← ${s.content?.name} ${s.content?.ok ? '✓' : '✗'}`
  if (s.role === 'thought') return `💭 思考`
  if (s.role === 'final') return `🏁 最终结论`
  return s.role
}

const catTag = (c) => ({
  market: 'primary', technical: 'success', news: 'warning',
  portfolio: 'info', risk: 'danger', execution: '',
}[c] || 'info')

const refreshAll = async () => {
  try { skills.value = await api.agentSkills() } catch (e) { console.error(e) }
  try { memory.value = await api.agentMemory() } catch (e) { console.error(e) }
  llmAvailable.value = lastRun.value?.llm_powered || false
}

const runScout = async () => {
  loading.value.scout = true
  try {
    lastRun.value = await api.agentRunScout()
    ElMessage.success(`Scout 完成 — ${lastRun.value.tool_calls_made} 次工具调用`)
    await refreshAll()
  } catch (e) { ElMessage.error(e.message) }
  finally { loading.value.scout = false }
}

const runGuardian = async () => {
  loading.value.guardian = true
  try {
    lastRun.value = await api.agentRunGuardian()
    ElMessage.success(`Guardian 完成`)
    await refreshAll()
  } catch (e) { ElMessage.error(e.message) }
  finally { loading.value.guardian = false }
}

const runResearch = async () => {
  loading.value.research = true
  try {
    lastRun.value = await api.agentRunResearch(researchSymbol.value)
    ElMessage.success(`Research 完成`)
    await refreshAll()
  } catch (e) { ElMessage.error(e.message) }
  finally { loading.value.research = false }
}

const runDailyBrief = async () => {
  loading.value.brief = true
  try {
    const data = await api.agentDailyBrief()
    ElMessage.success('日报生成完成')
    // Show scout run as the headline
    lastRun.value = {
      agent: 'orchestrator',
      goal: 'Daily brief: Scout + Guardian',
      status: 'success',
      llm_powered: data.llm_powered,
      tool_calls_made: (data.scout?.tool_calls_made || 0) + (data.guardian?.tool_calls_made || 0),
      duration_ms: (data.scout?.duration_ms || 0) + (data.guardian?.duration_ms || 0),
      final_answer: { scout: data.scout?.final, guardian: data.guardian?.final },
      trace: [],
    }
    await refreshAll()
  } catch (e) { ElMessage.error(e.message) }
  finally { loading.value.brief = false }
}

onMounted(refreshAll)
</script>
