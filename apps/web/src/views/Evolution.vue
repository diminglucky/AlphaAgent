<template>
  <div class="evolution-page">
    <div class="hero-card">
      <div>
        <div class="eyebrow">Auto Evolution</div>
        <h2>模型进化中枢</h2>
        <p>把每次扫描推荐变成可验证样本，到期后回看真实涨幅，并用结果校准下一版推荐概率。</p>
      </div>
      <div class="hero-actions">
        <el-button :loading="loading" @click="loadAll">刷新</el-button>
        <el-button type="primary" :loading="validating" @click="validateDue(false)">验证到期预测</el-button>
        <el-button type="success" plain :loading="autoCycling" @click="autoCycle">自动进化检查</el-button>
        <el-button type="warning" :loading="evolving" @click="evolve(false)">生成候选模型</el-button>
        <el-button type="danger" plain :loading="evolving" @click="evolve(true)">进化并启用</el-button>
      </div>
    </div>

    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      show-icon
    />

    <div class="metric-grid">
      <div class="metric-card active">
        <div class="metric-label">当前模型</div>
        <div class="metric-value">{{ activeModel?.version || '--' }}</div>
        <div class="metric-sub">{{ activeModel?.status || '未初始化' }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">已验证样本</div>
        <div class="metric-value">{{ counts.validated || 0 }}</div>
        <div class="metric-sub">总样本 {{ counts.total_predictions || 0 }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">待验证</div>
        <div class="metric-value">{{ counts.pending || 0 }}</div>
        <div class="metric-sub">已到期 {{ counts.due || 0 }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">命中率</div>
        <div class="metric-value">{{ pct(metrics.success_rate) }}</div>
        <div class="metric-sub">平均收益 {{ signed(metrics.avg_return_pct) }}%</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">概率校准误差</div>
        <div class="metric-value">{{ pct(metrics.calibration_error) }}</div>
        <div class="metric-sub">越低越好</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">LLM 用量</div>
        <div class="metric-value">{{ llmSummary.total_tokens || 0 }}</div>
        <div class="metric-sub">
          {{ llmSummary.calls || 0 }} 次调用 · ${{ fmtCost(llmSummary.estimated_cost_usd) }}
        </div>
      </div>
    </div>

    <el-row :gutter="16">
      <el-col :span="10">
        <el-card shadow="never" class="panel-card">
          <template #header>
            <div class="card-header">
              <span>按预测周期表现</span>
              <el-tag size="small" type="info" effect="plain">3 / 5 / 10 / 20 日</el-tag>
            </div>
          </template>
          <el-empty v-if="!horizonRows.length" description="暂无已验证样本" />
          <div v-else class="horizon-list">
            <div v-for="row in horizonRows" :key="row.horizon_days" class="horizon-item">
              <div class="horizon-title">
                <span>{{ row.horizon_days }} 日</span>
                <span>{{ row.sample_count }} 个样本</span>
              </div>
              <div class="horizon-bar">
                <el-progress
                  :percentage="Math.round((row.success_rate || 0) * 100)"
                  :stroke-width="8"
                  :show-text="false"
                  :color="progressColor(row.success_rate)"
                />
              </div>
              <div class="horizon-meta">
                <span>命中 {{ pct(row.success_rate) }}</span>
                <span>收盘收益 {{ signed(row.avg_return_pct) }}%</span>
                <span>最大涨幅 {{ signed(row.avg_max_return_pct) }}%</span>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>

      <el-col :span="14">
        <el-card shadow="never" class="panel-card">
          <template #header>
            <div class="card-header">
              <span>最近扫描批次</span>
              <span class="muted">每次扫描会自动写入预测样本</span>
            </div>
          </template>
          <el-table :data="summary?.latest_scan_runs || []" size="small" height="276">
            <el-table-column prop="id" label="批次" width="70" />
            <el-table-column label="时间" min-width="150">
              <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column prop="result_count" label="推荐" width="70" />
            <el-table-column prop="rejected_count" label="否决" width="70" />
            <el-table-column prop="llm_status" label="LLM" width="90" />
            <el-table-column label="耗时" width="90">
              <template #default="{ row }">{{ Math.round((row.elapsed_ms || 0) / 1000) }}s</template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="panel-card">
      <template #header>
        <div class="card-header">
          <span>最近两次扫描对比</span>
          <span class="muted">看哪些股票连续被推荐、哪些是新出现机会</span>
        </div>
      </template>
      <el-empty v-if="!comparison?.ready" description="至少需要两次已落库扫描结果" />
      <div v-else class="compare-panel">
        <div class="compare-stats">
          <div class="compare-stat">
            <span>本次推荐</span>
            <b>{{ comparison.counts?.base || 0 }}</b>
          </div>
          <div class="compare-stat new">
            <span>新增</span>
            <b>{{ comparison.counts?.new || 0 }}</b>
          </div>
          <div class="compare-stat overlap">
            <span>连续推荐</span>
            <b>{{ comparison.counts?.overlap || 0 }}</b>
          </div>
          <div class="compare-stat dropped">
            <span>掉队</span>
            <b>{{ comparison.counts?.dropped || 0 }}</b>
          </div>
        </div>
        <div class="compare-columns">
          <div class="compare-col">
            <div class="compare-title">新增机会</div>
            <div v-if="!comparison.new?.length" class="muted">无</div>
            <div v-for="s in comparison.new || []" :key="s.symbol" class="compare-stock">
              <span>{{ s.name || s.symbol }}</span>
              <b>{{ s.probability_pct }}%</b>
            </div>
          </div>
          <div class="compare-col">
            <div class="compare-title">连续推荐</div>
            <div v-if="!comparison.overlap?.length" class="muted">无</div>
            <div v-for="s in comparison.overlap || []" :key="s.symbol" class="compare-stock strong">
              <span>{{ s.name || s.symbol }}</span>
              <b>{{ s.probability_pct }}%</b>
            </div>
          </div>
          <div class="compare-col">
            <div class="compare-title">上次有、本次掉队</div>
            <div v-if="!comparison.dropped?.length" class="muted">无</div>
            <div v-for="s in comparison.dropped || []" :key="s.symbol" class="compare-stock muted-stock">
              <span>{{ s.name || s.symbol }}</span>
              <b>{{ s.probability_pct }}%</b>
            </div>
          </div>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="panel-card">
      <template #header>
        <div class="card-header">
          <span>自动进化决策记录</span>
          <span class="muted">记录自动晋升、阻断和回滚原因</span>
        </div>
      </template>
      <el-table :data="summary?.latest_evolution_runs || []" size="small" height="260">
        <el-table-column label="时间" min-width="150">
          <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="130">
          <template #default="{ row }">
            <el-tag :type="runStatusType(row.status)" size="small" effect="dark">
              {{ runStatusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="evaluated_predictions" label="样本" width="80" />
        <el-table-column label="命中率" width="90">
          <template #default="{ row }">{{ pct(row.success_rate) }}</template>
        </el-table-column>
        <el-table-column label="平均收益" width="100">
          <template #default="{ row }">{{ signed(row.avg_return_pct) }}%</template>
        </el-table-column>
        <el-table-column label="原因 / 决策" min-width="260">
          <template #default="{ row }">
            <span class="decision-text">{{ decisionText(row) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never" class="panel-card">
      <template #header>
        <div class="card-header">
          <span>预测样本</span>
          <div class="table-actions">
            <el-select v-model="filters.status" size="small" style="width:120px" @change="loadPredictions">
              <el-option label="全部" value="" />
              <el-option label="待验证" value="pending" />
              <el-option label="已验证" value="validated" />
            </el-select>
            <el-select v-model="filters.horizon_days" size="small" style="width:120px" @change="loadPredictions">
              <el-option label="全部周期" :value="null" />
              <el-option label="3 日" :value="3" />
              <el-option label="5 日" :value="5" />
              <el-option label="10 日" :value="10" />
              <el-option label="20 日" :value="20" />
            </el-select>
          </div>
        </div>
      </template>

      <el-table :data="predictions" v-loading="loadingPredictions" height="420">
        <el-table-column label="股票" min-width="150">
          <template #default="{ row }">
            <div class="stock-cell">
              <span class="stock-name">{{ row.name || row.symbol }}</span>
              <span class="stock-code">{{ row.symbol }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="周期" width="80">
          <template #default="{ row }">{{ row.horizon_days }} 日</template>
        </el-table-column>
        <el-table-column label="上涨概率" width="110">
          <template #default="{ row }">
            <span class="prob">{{ row.probability_pct }}%</span>
          </template>
        </el-table-column>
        <el-table-column label="目标" width="90">
          <template #default="{ row }">+{{ fmt(row.target_return_pct) }}%</template>
        </el-table-column>
        <el-table-column label="预期收益" width="100">
          <template #default="{ row }">
            <span :class="row.expected_return_pct >= 0 ? 'up' : 'down'">
              {{ signed(row.expected_return_pct) }}%
            </span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'validated' ? 'success' : 'info'" size="small" effect="dark">
              {{ row.status === 'validated' ? '已验证' : '待验证' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="结果" width="120">
          <template #default="{ row }">
            <span v-if="!row.outcome" class="muted">未到期</span>
            <el-tag v-else :type="row.outcome.success ? 'danger' : 'success'" size="small" effect="dark">
              {{ row.outcome.success ? '命中' : '未命中' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="真实收益" width="110">
          <template #default="{ row }">
            <span v-if="row.outcome" :class="row.outcome.close_return_pct >= 0 ? 'up' : 'down'">
              {{ signed(row.outcome.close_return_pct) }}%
            </span>
            <span v-else class="muted">--</span>
          </template>
        </el-table-column>
        <el-table-column label="到期" min-width="150">
          <template #default="{ row }">{{ fmtTime(row.due_at) }}</template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api.js'

defineOptions({ name: 'Evolution' })

const loading = ref(false)
const loadingPredictions = ref(false)
const validating = ref(false)
const evolving = ref(false)
const autoCycling = ref(false)
const error = ref('')
const summary = ref(null)
const predictions = ref([])
const comparison = ref(null)
const llmUsage = ref(null)
const filters = reactive({
  status: '',
  horizon_days: null,
})

const activeModel = computed(() => summary.value?.active_model || null)
const counts = computed(() => summary.value?.counts || {})
const metrics = computed(() => summary.value?.metrics || {})
const horizonRows = computed(() => metrics.value?.by_horizon || [])
const llmSummary = computed(() => llmUsage.value?.summary || {})

function fmt(v) {
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(2) : '--'
}

function pct(v) {
  const n = Number(v)
  return Number.isFinite(n) ? `${(n * 100).toFixed(1)}%` : '--'
}

function signed(v) {
  const n = Number(v)
  if (!Number.isFinite(n)) return '--'
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}`
}

function fmtTime(v) {
  if (!v) return '--'
  return new Date(v).toLocaleString('zh-CN', { hour12: false })
}

function fmtCost(v) {
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(6) : '0.000000'
}

function progressColor(v) {
  if (v >= 0.6) return '#f56c6c'
  if (v >= 0.4) return '#e6a23c'
  return '#67c23a'
}

function runStatusType(status) {
  if (status === 'auto_promoted' || status === 'completed') return 'success'
  if (status === 'auto_rolled_back') return 'danger'
  if (status === 'auto_blocked' || status === 'insufficient_data') return 'warning'
  return 'info'
}

function runStatusLabel(status) {
  const labels = {
    completed: '手动进化',
    insufficient_data: '样本不足',
    auto_blocked: '自动阻断',
    auto_promoted: '自动晋升',
    auto_rolled_back: '自动回滚',
  }
  return labels[status] || status || '--'
}

function decisionText(row) {
  const summary = row?.summary || {}
  const reasons = summary.reasons || []
  if (reasons.length) return reasons.join('；')
  if (summary.candidate_version) return `候选 ${summary.candidate_version} 已启用`
  if (summary.restored_model) return `恢复 ${summary.restored_model}，回滚 ${summary.rolled_back_model}`
  if (summary.reason) return summary.reason
  return '--'
}

async function loadSummary() {
  summary.value = await api.evolutionSummary()
}

async function loadPredictions() {
  loadingPredictions.value = true
  try {
    predictions.value = await api.evolutionPredictions({
      status: filters.status || undefined,
      horizon_days: filters.horizon_days || undefined,
      limit: 120,
    })
  } finally {
    loadingPredictions.value = false
  }
}

async function loadComparison() {
  comparison.value = await api.evolutionCompare()
}

async function loadUsage() {
  llmUsage.value = await api.llmUsage({ limit: 100 })
}

async function loadAll() {
  loading.value = true
  error.value = ''
  try {
    await Promise.all([loadSummary(), loadPredictions(), loadComparison(), loadUsage()])
  } catch (e) {
    error.value = `加载模型进化数据失败：${e.message}`
  } finally {
    loading.value = false
  }
}

async function validateDue(force) {
  validating.value = true
  error.value = ''
  try {
    const ret = await api.evolutionValidate({ limit: 300, force })
    ElMessage.success(`验证完成：检查 ${ret.checked}，验证 ${ret.validated}，跳过 ${ret.skipped}`)
    await loadAll()
  } catch (e) {
    error.value = `验证失败：${e.message}`
  } finally {
    validating.value = false
  }
}

async function evolve(promote) {
  evolving.value = true
  error.value = ''
  try {
    const ret = await api.evolutionEvolve({ promote })
    if (ret.status === 'insufficient_data') {
      ElMessage.warning(`样本不足：${ret.evaluated_predictions} / ${ret.min_samples}`)
    } else {
      ElMessage.success(promote ? '新模型已启用' : '候选模型已生成')
    }
    await loadAll()
  } catch (e) {
    error.value = `进化失败：${e.message}`
  } finally {
    evolving.value = false
  }
}

async function autoCycle() {
  autoCycling.value = true
  error.value = ''
  try {
    const ret = await api.evolutionAutoCycle()
    if (ret.status === 'auto_promoted') {
      ElMessage.success(`自动晋升完成：${ret.active_model?.version || '新模型'}`)
    } else if (ret.status === 'auto_rolled_back') {
      ElMessage.warning(`已自动回滚到：${ret.active_model?.version || '父模型'}`)
    } else if (ret.status === 'auto_blocked') {
      ElMessage.warning(`自动进化被阻断：${(ret.reasons || []).join('；') || '未达到质量门槛'}`)
    } else if (ret.status === 'insufficient_data') {
      ElMessage.info(`样本不足：${ret.evaluated_predictions} / ${ret.min_samples}`)
    } else {
      ElMessage.info(`自动进化状态：${ret.status}`)
    }
    await loadAll()
  } catch (e) {
    error.value = `自动进化检查失败：${e.message}`
  } finally {
    autoCycling.value = false
  }
}

onMounted(loadAll)
</script>

<style scoped>
.evolution-page { display:flex; flex-direction:column; gap:16px; }
.hero-card {
  display:flex;
  justify-content:space-between;
  align-items:flex-start;
  gap:18px;
  padding:22px;
  border-radius:18px;
  background:
    radial-gradient(circle at 12% 0%, rgba(64, 158, 255, .22), transparent 30%),
    linear-gradient(135deg, #18213d, #111827 55%, #1a1a2e);
  border:1px solid #2a3a64;
}
.eyebrow { color:#7db7ff; text-transform:uppercase; font-size:12px; letter-spacing:.14em; font-weight:800; }
.hero-card h2 { margin:6px 0; font-size:30px; color:#fff; }
.hero-card p { color:#a9b4c8; max-width:680px; line-height:1.7; }
.hero-actions { display:flex; gap:10px; flex-wrap:wrap; justify-content:flex-end; }
.metric-grid { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:12px; }
.metric-card { background:#1a1a2e; border:1px solid #2a2a4a; border-radius:14px; padding:16px; }
.metric-card.active { border-color:#409eff; background:#12223d; }
.metric-label { color:#909399; font-size:12px; }
.metric-value { margin-top:8px; color:#fff; font-size:28px; font-weight:900; }
.metric-sub { margin-top:6px; color:#7e8797; font-size:12px; }
.panel-card { border-radius:14px; }
.card-header { display:flex; justify-content:space-between; align-items:center; gap:12px; font-weight:800; }
.muted { color:#909399; font-size:12px; }
.horizon-list { display:flex; flex-direction:column; gap:16px; }
.horizon-item { background:#16162a; border:1px solid #2a2a4a; border-radius:12px; padding:14px; }
.horizon-title { display:flex; justify-content:space-between; color:#fff; font-weight:800; margin-bottom:10px; }
.horizon-meta { display:flex; justify-content:space-between; gap:8px; margin-top:8px; color:#909399; font-size:12px; }
.table-actions { display:flex; gap:8px; }
.stock-cell { display:flex; flex-direction:column; gap:2px; }
.stock-name { color:#fff; font-weight:800; }
.stock-code { color:#909399; font-size:12px; }
.prob { color:#7db7ff; font-weight:900; }
.compare-panel { display:flex; flex-direction:column; gap:14px; }
.compare-stats { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; }
.compare-stat { background:#16162a; border:1px solid #2a2a4a; border-radius:12px; padding:12px; display:flex; justify-content:space-between; align-items:center; }
.compare-stat span { color:#909399; font-size:12px; }
.compare-stat b { color:#fff; font-size:24px; }
.compare-stat.new { border-color:#409eff; }
.compare-stat.overlap { border-color:#f56c6c; }
.compare-stat.dropped { border-color:#67c23a; }
.compare-columns { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
.compare-col { background:#111827; border:1px solid #2a2a4a; border-radius:12px; padding:12px; min-height:120px; }
.compare-title { color:#fff; font-weight:800; margin-bottom:10px; }
.compare-stock { display:flex; justify-content:space-between; align-items:center; gap:10px; padding:8px 0; border-bottom:1px solid #253046; }
.compare-stock:last-child { border-bottom:none; }
.compare-stock span { color:#d7dce7; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.compare-stock b { color:#7db7ff; font-family:monospace; }
.compare-stock.strong b { color:#f56c6c; }
.compare-stock.muted-stock { opacity:.72; }
.decision-text { color:#d7dce7; font-size:12px; }

@media (max-width: 1100px) {
  .hero-card { flex-direction:column; }
  .hero-actions { justify-content:flex-start; }
  .metric-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .compare-stats { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .compare-columns { grid-template-columns:1fr; }
}
</style>
