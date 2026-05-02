<template>
  <div>
    <el-tabs v-model="activeTab" type="card">
      <!-- ===== TAB 1 — Single backtest ===== -->
      <el-tab-pane label="📊 单次回测" name="single">
        <el-card shadow="never" style="border-radius:8px; margin-bottom:20px">
          <el-form :model="sForm" inline label-width="90px">
            <el-form-item label="策略">
              <el-select v-model="sForm.strategy" style="width:180px">
                <el-option value="ma_crossover" label="均线交叉" />
                <el-option value="rsi_reversion" label="RSI 均值回归" />
                <el-option value="buy_hold" label="买入持有" />
              </el-select>
            </el-form-item>
            <el-form-item label="股票池">
              <el-select v-model="sForm.symbols" multiple style="width:320px" placeholder="选择标的">
                <el-option v-for="s in SYMBOLS" :key="s.value" :label="s.label" :value="s.value" />
              </el-select>
            </el-form-item>
            <el-form-item label="初始资金">
              <el-input-number v-model="sForm.initial_capital" :min="100000" :step="100000"
                :formatter="v => `¥${v.toLocaleString()}`" :parser="v => v.replace(/[¥,]/g, '')"
                style="width:180px" />
            </el-form-item>
            <el-form-item label="止损">
              <el-input-number v-model="sForm.stop_loss_pct" :min="0" :max="0.5" :step="0.01"
                :formatter="v => `${(v*100).toFixed(0)}%`" :parser="v => parseFloat(v)/100"
                style="width:100px" />
            </el-form-item>
            <el-form-item label="止盈">
              <el-input-number v-model="sForm.take_profit_pct" :min="0" :max="2" :step="0.05"
                :formatter="v => `${(v*100).toFixed(0)}%`" :parser="v => parseFloat(v)/100"
                style="width:100px" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="sLoading" @click="runSingle" :icon="VideoPlay">
                运行回测
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>

        <template v-if="sResult">
          <!-- Metric cards -->
          <el-row :gutter="16" style="margin-bottom:20px">
            <el-col :span="4" v-for="m in sMetricCards" :key="m.label">
              <el-card shadow="never" style="border-radius:8px; text-align:center; padding:8px 0">
                <p style="font-size:12px; color:#8c8c8c; margin-bottom:4px">{{ m.label }}</p>
                <p style="font-size:18px; font-weight:700" :style="{ color: m.color || '#333' }">{{ m.value }}</p>
              </el-card>
            </el-col>
          </el-row>

          <!-- Equity curve -->
          <el-card shadow="never" style="border-radius:8px; margin-bottom:20px">
            <template #header><span style="font-weight:600">📈 净值曲线</span></template>
            <v-chart :option="equityOption" style="height:320px" autoresize />
          </el-card>

          <!-- Trades table -->
          <el-card shadow="never" style="border-radius:8px">
            <template #header>
              <span style="font-weight:600">🗒 成交记录（{{ sResult.trades.length }} 笔）</span>
            </template>
            <el-table :data="sResult.trades" size="small" stripe max-height="320">
              <el-table-column prop="trade_id" label="ID" width="80" />
              <el-table-column prop="symbol" label="代码" width="120" />
              <el-table-column prop="entry_date" label="买入日" width="110" />
              <el-table-column label="买入价" width="90">
                <template #default="{ row }">{{ row.entry_price?.toFixed(2) }}</template>
              </el-table-column>
              <el-table-column prop="exit_date" label="卖出日" width="110" />
              <el-table-column label="卖出价" width="90">
                <template #default="{ row }">{{ row.exit_price?.toFixed(2) ?? '—' }}</template>
              </el-table-column>
              <el-table-column prop="quantity" label="数量" width="80" />
              <el-table-column label="盈亏">
                <template #default="{ row }">
                  <span :style="{ color: row.pnl >= 0 ? '#f5222d' : '#52c41a', fontWeight: 600 }">
                    {{ row.pnl >= 0 ? '+' : '' }}¥{{ row.pnl?.toLocaleString('zh-CN', { maximumFractionDigits: 0 }) }}
                    ({{ (row.pnl_pct * 100).toFixed(2) }}%)
                  </span>
                </template>
              </el-table-column>
              <el-table-column prop="reason" label="原因" />
            </el-table>
          </el-card>
        </template>
        <el-empty v-else-if="!sLoading" description="配置参数后点击「运行回测」" :image-size="80" />
      </el-tab-pane>

      <!-- ===== TAB 2 — Walk-forward ===== -->
      <el-tab-pane label="🔄 滚动验证" name="wf">
        <el-card shadow="never" style="border-radius:8px; margin-bottom:20px">
          <el-form :model="wfForm" inline label-width="100px">
            <el-form-item label="策略">
              <el-select v-model="wfForm.strategy" style="width:180px">
                <el-option value="ma_crossover" label="均线交叉" />
                <el-option value="rsi_reversion" label="RSI 均值回归" />
                <el-option value="buy_hold" label="买入持有" />
              </el-select>
            </el-form-item>
            <el-form-item label="股票池">
              <el-select v-model="wfForm.symbols" multiple style="width:320px" placeholder="选择标的">
                <el-option v-for="s in SYMBOLS" :key="s.value" :label="s.label" :value="s.value" />
              </el-select>
            </el-form-item>
            <el-form-item label="样本内 (天)">
              <el-input-number v-model="wfForm.in_sample_bars" :min="20" :max="756" :step="21" style="width:120px" />
            </el-form-item>
            <el-form-item label="样本外 (天)">
              <el-input-number v-model="wfForm.oos_bars" :min="5" :max="252" :step="21" style="width:120px" />
            </el-form-item>
            <el-form-item label="步进 (天)">
              <el-tooltip content="0 = 等于样本外长度（非重叠）">
                <el-input-number v-model="wfForm.step_bars" :min="0" :max="252" :step="21" style="width:120px" />
              </el-tooltip>
            </el-form-item>
            <el-form-item label="最少折叠">
              <el-input-number v-model="wfForm.min_folds" :min="1" :max="20" style="width:100px" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="wfLoading" @click="runWF" :icon="VideoPlay">
                运行验证
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>

        <template v-if="wfResult">
          <!-- Aggregate cards -->
          <el-row :gutter="16" style="margin-bottom:20px">
            <el-col :span="4" v-for="m in wfMetricCards" :key="m.label">
              <el-card shadow="never" style="border-radius:8px; text-align:center; padding:8px 0">
                <p style="font-size:12px; color:#8c8c8c; margin-bottom:4px">{{ m.label }}</p>
                <p style="font-size:18px; font-weight:700" :style="{ color: m.color || '#333' }">{{ m.value }}</p>
              </el-card>
            </el-col>
          </el-row>

          <!-- Consistency gauge -->
          <el-row :gutter="16" style="margin-bottom:20px">
            <el-col :span="8">
              <el-card shadow="never" style="border-radius:8px; text-align:center">
                <p style="font-weight:600; margin-bottom:8px">🎯 一致性评分</p>
                <el-progress
                  type="dashboard"
                  :percentage="Math.round(wfResult.aggregate.consistency_score * 100)"
                  :color="consistencyColor"
                  :stroke-width="14"
                />
                <p style="font-size:12px; color:#8c8c8c; margin-top:8px">
                  {{ consistencyLabel }}
                </p>
              </el-card>
            </el-col>
            <el-col :span="16">
              <el-card shadow="never" style="border-radius:8px">
                <template #header><span style="font-weight:600">📉 各折叠 OOS 收益率</span></template>
                <v-chart :option="foldBarOption" style="height:200px" autoresize />
              </el-card>
            </el-col>
          </el-row>

          <!-- Per-fold table -->
          <el-card shadow="never" style="border-radius:8px">
            <template #header><span style="font-weight:600">📋 逐折叠详情（{{ wfResult.n_folds }} 折）</span></template>
            <el-table :data="wfResult.folds" size="small" stripe>
              <el-table-column label="折叠" prop="fold" width="60" align="center" />
              <el-table-column label="样本内区间" width="210">
                <template #default="{ row }">{{ row.in_sample.start }} → {{ row.in_sample.end }}</template>
              </el-table-column>
              <el-table-column label="样本外区间" width="210">
                <template #default="{ row }">{{ row.oos.start }} → {{ row.oos.end }}</template>
              </el-table-column>
              <el-table-column label="收益率" width="100">
                <template #default="{ row }">
                  <span :style="{ color: row.metrics.total_return >= 0 ? '#f5222d' : '#52c41a', fontWeight: 600 }">
                    {{ row.metrics.total_return >= 0 ? '+' : '' }}{{ (row.metrics.total_return * 100).toFixed(2) }}%
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="Sharpe" width="90">
                <template #default="{ row }">{{ row.metrics.sharpe_ratio.toFixed(3) }}</template>
              </el-table-column>
              <el-table-column label="最大回撤" width="100">
                <template #default="{ row }">
                  <span style="color:#f5222d">-{{ (row.metrics.max_drawdown * 100).toFixed(2) }}%</span>
                </template>
              </el-table-column>
              <el-table-column label="胜率" width="80">
                <template #default="{ row }">{{ (row.metrics.win_rate * 100).toFixed(1) }}%</template>
              </el-table-column>
              <el-table-column label="交易次数" width="90" prop="metrics.total_trades" />
            </el-table>
          </el-card>
        </template>
        <el-empty v-else-if="!wfLoading" description="配置参数后点击「运行验证」" :image-size="80" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { VideoPlay } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart, BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { api } from '../api.js'

use([LineChart, BarChart, GridComponent, TooltipComponent, DataZoomComponent, CanvasRenderer])

const SYMBOLS = [
  { value: '600519.SH', label: '600519 贵州茅台' },
  { value: '000001.SZ', label: '000001 平安银行' },
  { value: '300750.SZ', label: '300750 宁德时代' },
  { value: '600036.SH', label: '600036 招商银行' },
  { value: '601318.SH', label: '601318 中国平安' },
  { value: '000858.SZ', label: '000858 五粮液' },
  { value: '000333.SZ', label: '000333 美的集团' },
  { value: '601166.SH', label: '601166 兴业银行' },
]

// ── Tab state ──
const activeTab = ref('single')

// ── Single backtest ──
const sForm = ref({
  strategy: 'ma_crossover',
  symbols: ['600519.SH'],
  initial_capital: 1000000,
  stop_loss_pct: 0.08,
  take_profit_pct: 0.20,
})
const sLoading = ref(false)
const sResult = ref(null)

const pct = (v, d = 2) => `${(v >= 0 ? '+' : '') + (v * 100).toFixed(d)}%`
const pctAbs = (v, d = 2) => `${(Math.abs(v) * 100).toFixed(d)}%`
const fmtY = v => `¥${Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`

const sMetricCards = computed(() => {
  if (!sResult.value) return []
  const m = sResult.value.metrics
  return [
    { label: '总收益率', value: pct(m.total_return), color: m.total_return >= 0 ? '#f5222d' : '#52c41a' },
    { label: '年化收益', value: pct(m.annual_return), color: m.annual_return >= 0 ? '#f5222d' : '#52c41a' },
    { label: 'Sharpe', value: m.sharpe_ratio.toFixed(3), color: m.sharpe_ratio >= 1 ? '#52c41a' : m.sharpe_ratio >= 0 ? '#faad14' : '#f5222d' },
    { label: '最大回撤', value: '-' + pctAbs(m.max_drawdown), color: '#f5222d' },
    { label: '胜率', value: pctAbs(m.win_rate, 1) },
    { label: '盈亏比', value: m.profit_factor.toFixed(2) + 'x' },
  ]
})

const equityOption = computed(() => {
  if (!sResult.value) return {}
  const curve = sResult.value.equity_curve || []
  return {
    tooltip: { trigger: 'axis', formatter: p => `${p[0].name}<br/>¥${Number(p[0].value).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}` },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 20 }],
    grid: { top: 16, right: 16, bottom: 48, left: 72 },
    xAxis: { type: 'category', data: curve.map(p => p.date), axisLabel: { fontSize: 11 } },
    yAxis: { type: 'value', axisLabel: { formatter: v => `¥${(v / 10000).toFixed(0)}万` } },
    series: [{
      type: 'line',
      data: curve.map(p => p.value),
      smooth: true,
      symbol: 'none',
      lineStyle: { width: 2, color: '#1890ff' },
      areaStyle: { color: 'rgba(24,144,255,0.08)' },
    }],
  }
})

const runSingle = async () => {
  if (!sForm.value.symbols.length) return ElMessage.warning('请至少选一只股票')
  sLoading.value = true
  sResult.value = null
  try {
    sResult.value = await api.backtestRun(sForm.value)
    if (!sResult.value.ok) ElMessage.error(sResult.value.error || '回测失败')
    else ElMessage.success('回测完成')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    sLoading.value = false
  }
}

// ── Walk-forward ──
const wfForm = ref({
  strategy: 'ma_crossover',
  symbols: ['600519.SH'],
  in_sample_bars: 252,
  oos_bars: 63,
  step_bars: 0,
  min_folds: 2,
  initial_capital: 1000000,
  stop_loss_pct: 0.08,
  take_profit_pct: 0.20,
})
const wfLoading = ref(false)
const wfResult = ref(null)

const wfMetricCards = computed(() => {
  if (!wfResult.value) return []
  const a = wfResult.value.aggregate
  return [
    { label: '折叠数', value: wfResult.value.n_folds, color: '#1890ff' },
    { label: 'OOS 平均收益', value: pct(a.oos_total_return_mean), color: a.oos_total_return_mean >= 0 ? '#f5222d' : '#52c41a' },
    { label: 'OOS Sharpe', value: a.oos_sharpe_mean.toFixed(3) },
    { label: 'OOS 最大回撤', value: '-' + pctAbs(a.oos_max_drawdown_mean), color: '#f5222d' },
    { label: '盈利折叠占比', value: pctAbs(a.pct_profitable_folds, 1), color: a.pct_profitable_folds >= 0.6 ? '#52c41a' : '#faad14' },
    { label: '一致性评分', value: (a.consistency_score * 100).toFixed(1) + '%', color: a.consistency_score >= 0.5 ? '#52c41a' : '#faad14' },
  ]
})

const consistencyColor = computed(() => {
  if (!wfResult.value) return '#d9d9d9'
  const c = wfResult.value.aggregate.consistency_score
  if (c >= 0.6) return '#52c41a'
  if (c >= 0.35) return '#faad14'
  return '#ff4d4f'
})

const consistencyLabel = computed(() => {
  if (!wfResult.value) return ''
  const c = wfResult.value.aggregate.consistency_score
  if (c >= 0.6) return '策略稳健，可考虑实盘'
  if (c >= 0.35) return '策略一般，建议继续优化'
  return '策略不稳定，不建议实盘'
})

const foldBarOption = computed(() => {
  if (!wfResult.value) return {}
  const folds = wfResult.value.folds
  const colors = folds.map(f => f.metrics.total_return >= 0 ? '#ff4d4f' : '#52c41a')
  return {
    tooltip: { trigger: 'axis', formatter: p => `第 ${p[0].name + 1} 折：${pct(p[0].value)}` },
    grid: { top: 8, right: 8, bottom: 32, left: 64 },
    xAxis: { type: 'category', data: folds.map(f => `F${f.fold}`), axisLabel: { fontSize: 11 } },
    yAxis: { type: 'value', axisLabel: { formatter: v => `${(v * 100).toFixed(1)}%` } },
    series: [{
      type: 'bar',
      data: folds.map((f, i) => ({ value: f.metrics.total_return, itemStyle: { color: colors[i] } })),
    }],
  }
})

const runWF = async () => {
  if (!wfForm.value.symbols.length) return ElMessage.warning('请至少选一只股票')
  wfLoading.value = true
  wfResult.value = null
  try {
    wfResult.value = await api.backtestWalkForward(wfForm.value)
    if (!wfResult.value.ok) ElMessage.error(wfResult.value.error || '验证失败')
    else ElMessage.success(`完成 ${wfResult.value.n_folds} 个折叠`)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    wfLoading.value = false
  }
}
</script>
