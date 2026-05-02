<template>
  <div>
    <!-- Search bar -->
    <el-card shadow="never" style="margin-bottom:20px; border-radius:8px">
      <el-form inline>
        <el-form-item label="股票代码">
          <el-select v-model="symbol" filterable placeholder="选择股票" style="width:200px">
            <el-option v-for="s in SYMBOLS" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="持仓背景（可选）">
          <el-input v-model="context" placeholder="如：当前仓位5%，上限20%" style="width:260px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="runAnalysis" :icon="MagicStick">
            开始分析
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <div v-if="report">
      <!-- Action banner -->
      <el-alert
        :title="report.summary"
        :type="alertType"
        :description="report.approved ? '风控已通过 ✓' : '⚠️ 风控拦截 — 建议人工复核'"
        show-icon
        :closable="false"
        style="margin-bottom:20px; font-size:15px"
      />

      <el-row :gutter="16" style="margin-bottom:20px">
        <!-- Confidence + meta -->
        <el-col :span="8">
          <el-card shadow="never" style="border-radius:8px; text-align:center; padding:16px 0">
            <p style="color:#8c8c8c; font-size:13px; margin-bottom:8px">综合置信度</p>
            <el-progress
              type="dashboard"
              :percentage="Math.round(report.confidence * 100)"
              :color="confColor"
              :stroke-width="12"
            />
            <p style="margin-top:12px; font-size:12px; color:#8c8c8c">
              {{ report.llm_powered ? '🤖 LLM 增强分析' : '📐 规则引擎分析' }}
            </p>
          </el-card>
        </el-col>

        <!-- Risk flags -->
        <el-col :span="8">
          <el-card shadow="never" style="border-radius:8px; height:100%">
            <p style="font-weight:600; margin-bottom:12px">⚑ 风险标记</p>
            <div v-if="report.risk_flags.length">
              <el-tag
                v-for="f in report.risk_flags"
                :key="f"
                type="danger"
                style="margin:4px"
              >{{ f }}</el-tag>
            </div>
            <el-empty v-else description="无风险标记" :image-size="50" />
          </el-card>
        </el-col>

        <!-- Agent votes summary -->
        <el-col :span="8">
          <el-card shadow="never" style="border-radius:8px; height:100%">
            <p style="font-weight:600; margin-bottom:12px">🗳 Agent 投票</p>
            <div v-for="(val, agent) in agentVotes" :key="agent" style="margin-bottom:8px">
              <div style="display:flex; justify-content:space-between; font-size:13px">
                <span>{{ agentLabel(agent) }}</span>
                <el-tag :type="voteType(val.view)" size="small">{{ viewLabel(val.view) }}</el-tag>
              </div>
              <el-progress
                :percentage="Math.round(val.confidence * 100)"
                :stroke-width="4"
                :show-text="false"
                :color="voteColor(val.view)"
                style="margin-top:4px"
              />
            </div>
          </el-card>
        </el-col>
      </el-row>

      <!-- Full reasoning -->
      <el-card shadow="never" style="border-radius:8px; margin-bottom:20px">
        <template #header><span style="font-weight:600">📝 详细分析报告</span></template>
        <el-tabs>
          <el-tab-pane label="综合理由">
            <pre style="white-space:pre-wrap; font-family:inherit; font-size:14px; line-height:1.8; color:#333">{{ report.reasoning }}</pre>
          </el-tab-pane>
          <el-tab-pane v-for="agent in agentOrder" :key="agent" :label="agentLabel(agent)">
            <div v-if="report.components[agent]">
              <el-descriptions :column="2" size="small" border style="margin-bottom:12px">
                <el-descriptions-item label="观点">
                  <el-tag :type="voteType(report.components[agent].view)">
                    {{ viewLabel(report.components[agent].view) }}
                  </el-tag>
                </el-descriptions-item>
                <el-descriptions-item label="置信度">
                  {{ pct(report.components[agent].confidence) }}
                </el-descriptions-item>
              </el-descriptions>
              <p style="font-size:14px; color:#555; line-height:1.8; margin-bottom:12px">
                {{ report.components[agent].reasoning }}
              </p>
              <div v-if="report.components[agent].key_points?.length">
                <p style="font-weight:600; margin-bottom:6px; font-size:13px">关键要点：</p>
                <ul style="padding-left:20px; color:#555; font-size:13px; line-height:2">
                  <li v-for="p in report.components[agent].key_points" :key="p">{{ p }}</li>
                </ul>
              </div>
            </div>
          </el-tab-pane>
        </el-tabs>
      </el-card>
    </div>

    <el-empty v-else-if="!loading" description="选择股票后点击「开始分析」" :image-size="80" />
  </div>
</template>

<script setup>
import { ref, computed, markRaw } from 'vue'
import { MagicStick } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { api } from '../api.js'

const SYMBOLS = [
  { value: '600519.SH', label: '600519 贵州茅台' },
  { value: '000001.SZ', label: '000001 平安银行' },
  { value: '300750.SZ', label: '300750 宁德时代' },
  { value: '000858.SZ', label: '000858 五粮液' },
  { value: '601318.SH', label: '601318 中国平安' },
  { value: '600036.SH', label: '600036 招商银行' },
  { value: '601166.SH', label: '601166 兴业银行' },
  { value: '000333.SZ', label: '000333 美的集团' },
]

const symbol = ref('600519.SH')
const context = ref('')
const loading = ref(false)
const report = ref(null)

const agentOrder = ['TechnicalAnalyst', 'NewsAnalyst', 'FundamentalAnalyst', 'RiskOfficer']

const agentVotes = computed(() => {
  if (!report.value) return {}
  return Object.fromEntries(
    agentOrder
      .filter(a => report.value.components[a])
      .map(a => [a, report.value.components[a]])
  )
})

const alertType = computed(() => {
  if (!report.value) return 'info'
  if (!report.value.approved) return 'warning'
  const a = report.value.action
  return a === 'BUY' ? 'error' : a === 'SELL' ? 'success' : 'info'
})

const confColor = computed(() => {
  const c = report.value?.confidence ?? 0
  if (c >= 0.7) return '#52c41a'
  if (c >= 0.5) return '#faad14'
  return '#ff4d4f'
})

const pct = v => `${(v * 100).toFixed(0)}%`

const agentLabel = a => ({
  TechnicalAnalyst: '技术分析师',
  NewsAnalyst: '新闻分析师',
  FundamentalAnalyst: '基本面分析师',
  RiskOfficer: '风控官',
}[a] || a)

const viewLabel = v => ({ BULLISH: '看多', NEUTRAL: '中性', BEARISH: '看空' }[v] || v)
const voteType = v => ({ BULLISH: 'danger', NEUTRAL: 'info', BEARISH: 'success' }[v] || 'info')
const voteColor = v => ({ BULLISH: '#ff4d4f', NEUTRAL: '#1890ff', BEARISH: '#52c41a' }[v] || '#1890ff')

const runAnalysis = async () => {
  loading.value = true
  report.value = null
  try {
    report.value = await api.analyze(symbol.value, context.value || null)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}
</script>
