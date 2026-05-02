<template>
  <div>
    <el-card shadow="never" style="border-radius:8px; margin-bottom:20px">
      <el-row justify="space-between" align="middle">
        <el-col :span="12">
          <el-radio-group v-model="freq" @change="loadBars">
            <el-radio-button value="1d">日线</el-radio-button>
            <el-radio-button value="1m">分钟</el-radio-button>
          </el-radio-group>
        </el-col>
        <el-col :span="12" style="text-align:right">
          <el-select v-model="symbol" @change="loadBars" style="width:200px">
            <el-option v-for="s in SYMBOLS" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </el-col>
      </el-row>
    </el-card>

    <!-- Quote summary -->
    <el-row :gutter="16" style="margin-bottom:20px">
      <el-col :span="4" v-for="q in quoteCells" :key="q.label">
        <el-card shadow="never" style="border-radius:8px; text-align:center; padding:8px 0">
          <p style="font-size:12px; color:#8c8c8c">{{ q.label }}</p>
          <p style="font-size:18px; font-weight:700; margin-top:4px" :style="{ color: q.color }">{{ q.value }}</p>
        </el-card>
      </el-col>
    </el-row>

    <!-- K-line / bar table -->
    <el-card shadow="never" style="border-radius:8px">
      <template #header>
        <span style="font-weight:600">K 线数据</span>
        <el-tag size="small" style="margin-left:8px">{{ symbol }}</el-tag>
      </template>
      <el-table :data="bars" v-loading="loading" size="small" height="420">
        <el-table-column prop="trade_date" label="日期" width="110" />
        <el-table-column prop="open" label="开盘" />
        <el-table-column prop="high" label="最高" />
        <el-table-column prop="low" label="最低" />
        <el-table-column prop="close" label="收盘">
          <template #default="{ row }">
            <span :style="{ color: row.close >= row.open ? '#f5222d' : '#52c41a', fontWeight: 600 }">
              {{ row.close }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="volume" label="成交量" />
        <el-table-column label="涨跌幅">
          <template #default="{ row }">
            <span :style="{ color: row.pct_change >= 0 ? '#f5222d' : '#52c41a' }">
              {{ row.pct_change >= 0 ? '+' : '' }}{{ row.pct_change }}%
            </span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
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
const freq = ref('1d')
const bars = ref([])
const loading = ref(false)
const quote = ref(null)

const quoteCells = computed(() => {
  const q = quote.value || {}
  const last = bars.value.at(-1)
  const prev = bars.value.at(-2)
  const chg = last && prev ? ((last.close - prev.close) / prev.close * 100).toFixed(2) : '–'
  const color = parseFloat(chg) >= 0 ? '#f5222d' : '#52c41a'
  return [
    { label: '最新价', value: last?.close ?? '–', color },
    { label: '今日涨跌', value: chg === '–' ? '–' : `${chg >= 0 ? '+' : ''}${chg}%`, color },
    { label: '最高', value: last?.high ?? '–', color: '#f5222d' },
    { label: '最低', value: last?.low ?? '–', color: '#52c41a' },
    { label: '成交量', value: last?.volume?.toLocaleString() ?? '–', color: '#333' },
    { label: '数据条数', value: bars.value.length, color: '#1890ff' },
  ]
})

const loadBars = async () => {
  loading.value = true
  bars.value = []
  try {
    const data = await api.bars(symbol.value, freq.value)
    const raw = Array.isArray(data) ? data : (data.bars || [])
    bars.value = raw.map((b, i) => ({
      ...b,
      pct_change: i === 0
        ? 0
        : ((b.close - raw[i - 1].close) / raw[i - 1].close * 100).toFixed(2),
    })).reverse()
  } catch {
    bars.value = []
  } finally {
    loading.value = false
  }
}

onMounted(loadBars)
</script>
