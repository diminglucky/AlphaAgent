<template>
  <div>
    <el-card shadow="never" style="margin-bottom:16px">
      <template #header>
        <span style="font-weight:600">🤖 LLM API 配置</span>
        <el-tag v-if="effective.is_llm_available" type="success" size="small" style="margin-left:8px">
          ✓ 已就绪
        </el-tag>
        <el-tag v-else type="info" size="small" style="margin-left:8px">
          未配置（Agent 走 Fallback）
        </el-tag>
      </template>

      <el-form label-width="120px" :model="form" style="max-width:720px">
        <el-form-item label="服务提供商">
          <el-radio-group v-model="form.provider" @change="onProviderChange">
            <el-radio-button v-for="p in providerList" :key="p" :label="p">
              {{ presets[p]?.label || p }}
            </el-radio-button>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="Base URL">
          <el-input v-model="form.base_url" placeholder="留空使用默认" clearable />
          <div v-if="presets[form.provider]?.base_url" style="font-size:12px; color:#999; margin-top:4px">
            默认: <code>{{ presets[form.provider].base_url }}</code>
          </div>
        </el-form-item>

        <el-form-item label="模型">
          <el-select v-model="form.model" filterable allow-create style="width:100%"
                     placeholder="选择或输入自定义模型名">
            <el-option v-for="m in (presets[form.provider]?.models || [])"
                       :key="m" :label="m" :value="m" />
          </el-select>
        </el-form-item>

        <el-form-item label="API Key">
          <el-input
            v-model="form.api_key"
            :type="showKey ? 'text' : 'password'"
            :placeholder="effective.api_key_set ? `已设置（${effective.api_key_preview}），留空保持` : '粘贴 sk-... 开头的 key'"
            clearable
          >
            <template #suffix>
              <el-icon @click="showKey = !showKey" style="cursor:pointer">
                <View v-if="!showKey" /><Hide v-else />
              </el-icon>
            </template>
          </el-input>
          <div style="font-size:12px; color:#999; margin-top:4px">
            {{ presets[form.provider]?.key_help || '' }}
          </div>
        </el-form-item>

        <el-form-item label="Temperature">
          <el-slider v-model="form.temperature" :min="0" :max="1" :step="0.1" show-input />
        </el-form-item>

        <el-form-item label="超时（秒）">
          <el-input-number v-model="form.timeout" :min="5" :max="120" :step="5" />
        </el-form-item>

        <el-form-item>
          <el-button type="primary" @click="save" :loading="saving">💾 保存</el-button>
          <el-button type="success" @click="runTest('quick')" :loading="testing === 'quick'">
            ⚡ 快速测试 (1-3s)
          </el-button>
          <el-button type="warning" @click="runTest('standard')" :loading="testing === 'standard'">
            🧪 标准测试 (2-4s)
          </el-button>
          <el-button type="info" @click="runTest('full')" :loading="testing === 'full'">
            🔬 完整测试 (5-15s)
          </el-button>
          <el-button @click="reset" :loading="saving">↩️ 重置</el-button>
        </el-form-item>
        <el-form-item>
          <div style="font-size:12px; color:#999">
            <strong>快速</strong>：仅 chat 验证 key 可用 ｜
            <strong>标准</strong>：+ Function Calling 验证 ｜
            <strong>完整</strong>：+ 完整 Agent ReAct 循环
          </div>
        </el-form-item>
      </el-form>

      <el-alert type="info" :closable="false" show-icon>
        <template #title>
          <strong>API Key 安全说明</strong>
        </template>
        Key 加密保存到本地 <code>data/llm_runtime.json</code>，未上传任何外部服务器。
        生产环境建议改用环境变量 <code>QUANT_LLM_API_KEY</code> 或密钥管理系统。
      </el-alert>
    </el-card>

    <!-- Test results -->
    <el-card v-if="testResult" shadow="never">
      <template #header>
        <span style="font-weight:600">🧪 测试结果</span>
        <el-tag :type="overallOk ? 'success' : 'danger'" size="small" style="margin-left:8px">
          {{ overallOk ? '全部通过' : '失败' }}
        </el-tag>
      </template>

      <div style="margin-bottom:12px">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="Provider">{{ testResult.provider }}</el-descriptions-item>
          <el-descriptions-item label="Model">{{ testResult.model }}</el-descriptions-item>
          <el-descriptions-item label="Base URL" :span="2">
            <code>{{ testResult.base_url || '(default)' }}</code>
          </el-descriptions-item>
        </el-descriptions>
      </div>

      <el-table :data="testRows" size="small" border>
        <el-table-column label="测试" width="180">
          <template #default="{ row }">{{ row.label }}</template>
        </el-table-column>
        <el-table-column label="结果" width="90">
          <template #default="{ row }">
            <el-tag :type="row.ok ? 'success' : 'danger'" size="small">
              {{ row.ok ? '✓ 通过' : '✗ 失败' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="100">
          <template #default="{ row }">
            {{ row.duration_ms ? row.duration_ms + ' ms' : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="详情">
          <template #default="{ row }">
            <pre style="margin:0; font-size:11px; white-space:pre-wrap; max-height:200px; overflow:auto">{{ row.detail }}</pre>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { View, Hide } from '@element-plus/icons-vue'
import { api } from '../api.js'

const presets = ref({})
const providerList = ref([])
const effective = ref({})
const form = ref({
  provider: 'keyword',
  model: '',
  api_key: '',
  base_url: '',
  temperature: 0.2,
  timeout: 30,
})
const showKey = ref(false)
const saving = ref(false)
const testing = ref('')   // '' | 'quick' | 'standard' | 'full'
const testResult = ref(null)

const onProviderChange = (val) => {
  const p = presets.value[val]
  if (p) {
    if (!form.value.model && p.default_model) form.value.model = p.default_model
    if (!form.value.base_url && p.base_url) form.value.base_url = p.base_url
  }
}

const load = async () => {
  const data = await api.llmConfigGet()
  presets.value = data.presets || {}
  providerList.value = Object.keys(data.presets || {})
  effective.value = data.effective || {}
  const ov = data.runtime_override || {}
  form.value = {
    provider: ov.provider || effective.value.provider || 'keyword',
    model: ov.model || effective.value.model || '',
    api_key: '',  // never echo back
    base_url: ov.base_url || effective.value.base_url || '',
    temperature: ov.temperature ?? effective.value.temperature ?? 0.2,
    timeout: ov.timeout || effective.value.timeout || 30,
  }
}

const save = async () => {
  saving.value = true
  try {
    const payload = { ...form.value }
    if (!payload.api_key) delete payload.api_key  // don't overwrite with empty
    if (!payload.base_url) delete payload.base_url
    await api.llmConfigSet(payload)
    ElMessage.success('已保存')
    await load()
  } catch (e) { ElMessage.error(e.message) }
  finally { saving.value = false }
}

const reset = async () => {
  saving.value = true
  try {
    await api.llmConfigReset()
    ElMessage.success('已重置为环境变量/默认值')
    await load()
  } catch (e) { ElMessage.error(e.message) }
  finally { saving.value = false }
}

const runTest = async (level = 'quick') => {
  testing.value = level
  testResult.value = null
  try {
    testResult.value = await api.llmTest(level)
    const ok = overallOk.value
    ElMessage[ok ? 'success' : 'warning'](ok ? '✓ 测试通过' : '测试存在失败项，查看详情')
  } catch (e) { ElMessage.error(e.message) }
  finally { testing.value = '' }
}

const testRows = computed(() => {
  if (!testResult.value?.tests) return []
  const labels = {
    chat: '基础对话',
    tool_calling: '工具调用 (Function Calling)',
    agent_run: 'ResearchAgent 端到端运行',
  }
  return Object.entries(testResult.value.tests).map(([key, val]) => ({
    label: labels[key] || key,
    ok: val.ok,
    duration_ms: val.duration_ms,
    detail: val.error || JSON.stringify(
      Object.fromEntries(Object.entries(val).filter(([k]) => !['ok', 'duration_ms'].includes(k))),
      null, 2
    ),
  }))
})

const overallOk = computed(() => {
  if (!testResult.value?.tests) return false
  return Object.values(testResult.value.tests).every(t => t.ok)
})

onMounted(load)
</script>
