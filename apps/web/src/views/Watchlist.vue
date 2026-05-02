<template>
  <div>
    <el-card shadow="never" style="border-radius:8px; margin-bottom:20px">
      <template #header>
        <div style="display:flex; align-items:center; justify-content:space-between">
          <span style="font-weight:600">⭐ 自选股管理</span>
          <span style="font-size:12px; color:#999">添加/删除后会立即作用于实时分析与建议</span>
        </div>
      </template>

      <!-- Add form -->
      <el-form inline @submit.prevent="add">
        <el-form-item label="股票代码">
          <el-input
            v-model="newSymbol"
            placeholder="如 600519.SH"
            style="width:200px"
            @keydown.enter.prevent="add"
          />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="newNote" placeholder="可选，如：长线持有" style="width:240px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="adding" @click="add" :icon="Plus">添加到自选</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- Items table -->
    <el-card shadow="never" style="border-radius:8px">
      <template #header>
        <span style="font-weight:600">📋 当前自选 ({{ items.length }})</span>
        <span v-if="!items.length" style="float:right; font-size:12px; color:#999">
          为空时使用默认列表
        </span>
      </template>
      <el-table :data="items" v-loading="loading" size="small" stripe empty-text="暂无自选，使用默认列表">
        <el-table-column prop="symbol" label="代码" width="160">
          <template #default="{ row }">
            <strong>{{ row.symbol }}</strong>
          </template>
        </el-table-column>
        <el-table-column prop="note" label="备注" />
        <el-table-column label="实时" width="160">
          <template #default="{ row }">
            <span v-if="quotesMap[row.symbol]"
              :style="{ color: quotesMap[row.symbol].change >= 0 ? '#f5222d' : '#52c41a', fontWeight: 600 }">
              ¥{{ quotesMap[row.symbol].last_price.toFixed(2) }}
              ({{ quotesMap[row.symbol].change_pct >= 0 ? '+' : '' }}{{ quotesMap[row.symbol].change_pct.toFixed(2) }}%)
            </span>
            <span v-else style="color:#bbb">–</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="加入时间" width="170" />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="$router.push(`/analysis?symbol=${row.symbol}`)">分析</el-button>
            <el-button link type="danger" size="small" @click="remove(row.symbol)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api.js'
import { quotesMap } from '../realtimeStore.js'

const items = ref([])
const newSymbol = ref('')
const newNote = ref('')
const loading = ref(false)
const adding = ref(false)

const load = async () => {
  loading.value = true
  try {
    const data = await api.watchlistList()
    items.value = data.items || []
  } catch (e) {
    ElMessage.error('加载自选股失败：' + e.message)
  } finally {
    loading.value = false
  }
}

const add = async () => {
  const sym = newSymbol.value.trim().toUpperCase()
  if (!sym) {
    ElMessage.warning('请输入股票代码')
    return
  }
  adding.value = true
  try {
    await api.watchlistAdd(sym, newNote.value)
    ElMessage.success(`已添加 ${sym}`)
    newSymbol.value = ''
    newNote.value = ''
    await load()
  } catch (e) {
    ElMessage.error('添加失败：' + e.message)
  } finally {
    adding.value = false
  }
}

const remove = async (sym) => {
  await ElMessageBox.confirm(`从自选股中移除 ${sym}？`, '确认', { type: 'warning' })
  try {
    await api.watchlistRemove(sym)
    ElMessage.success(`已移除 ${sym}`)
    await load()
  } catch (e) {
    ElMessage.error('删除失败：' + e.message)
  }
}

onMounted(load)
</script>
