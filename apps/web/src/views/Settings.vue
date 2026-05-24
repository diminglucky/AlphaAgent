<template>
  <div class="settings-page">
    <h2>系统设置</h2>

    <!-- LLM 配置 -->
    <div class="settings-card">
      <div class="card-header">
        <span class="card-title">🤖 大模型配置</span>
        <el-tag :type="llmStatus.is_llm_available ? 'success' : 'danger'" size="small" effect="dark">
          {{ llmStatus.is_llm_available ? '✓ 已连接' : '✗ 未配置' }}
        </el-tag>
      </div>

      <!-- 快速选择预设 -->
      <div class="preset-row">
        <span class="field-label">快速选择</span>
        <div class="preset-btns">
          <el-button
            v-for="(preset, key) in presets"
            :key="key"
            size="small"
            :type="llmForm.provider === key ? 'primary' : ''"
            @click="applyPreset(key)"
          >
            {{ preset.label }}
          </el-button>
        </div>
      </div>

      <el-divider style="margin:12px 0" />

      <el-form :model="llmForm" label-width="100px" size="default">
        <el-form-item label="API Key">
          <el-input
            v-model="llmForm.api_key"
            type="password"
            show-password
            placeholder="sk-xxxxxxxxxxxxxxxx"
            clearable
          />
          <div class="field-hint" v-if="currentPreset?.key_help">
            {{ currentPreset.key_help }}
          </div>
        </el-form-item>

        <el-form-item label="API 地址">
          <el-input
            v-model="llmForm.base_url"
            placeholder="https://api.deepseek.com/v1"
            clearable
          />
          <div class="field-hint">
            只填到 <code>/v1</code> 结尾，不要加 <code>/chat/completions</code>
          </div>
        </el-form-item>

        <el-form-item label="模型名称">
          <el-select
            v-if="currentPreset?.models?.length"
            v-model="llmForm.model"
            allow-create
            filterable
            placeholder="选择或输入模型名称"
            style="width:100%"
          >
            <el-option
              v-for="m in currentPreset.models"
              :key="m"
              :label="m"
              :value="m"
            />
          </el-select>
          <el-input
            v-else
            v-model="llmForm.model"
            placeholder="如 deepseek-chat / gpt-4o-mini"
            clearable
          />
        </el-form-item>

        <el-form-item label="温度">
          <div style="display:flex;align-items:center;gap:12px;width:100%">
            <el-slider
              v-model="llmForm.temperature"
              :min="0" :max="1" :step="0.05"
              style="flex:1"
            />
            <span style="color:#909399;font-size:13px;width:36px;text-align:right">
              {{ llmForm.temperature?.toFixed(2) }}
            </span>
          </div>
          <div class="field-hint">越低越确定（推荐 0.1~0.3），越高越有创意</div>
        </el-form-item>

        <el-form-item label="超时（秒）">
          <el-input-number
            v-model="llmForm.timeout"
            :min="10" :max="300" :step="10"
            style="width:160px"
          />
          <div class="field-hint">Agent 分析需要多次工具调用，建议 120 秒以上</div>
        </el-form-item>
      </el-form>

      <div class="card-actions">
        <el-button type="primary" :loading="saving" @click="saveLLMConfig">
          💾 保存配置
        </el-button>
        <el-button type="success" :loading="testing" @click="testLLM">
          🔌 测试连接
        </el-button>
        <el-button @click="resetLLMConfig" plain>
          重置为默认
        </el-button>
      </div>

      <!-- 测试结果 -->
      <div v-if="testResult" class="test-result" :class="testResult.ok ? 'test-ok' : 'test-fail'">
        <div class="tr-header">
          {{ testResult.ok ? '✓ 连接成功' : '✗ 连接失败' }}
          <span style="font-size:12px;color:#909399;margin-left:8px">
            {{ testResult.duration_ms }}ms
          </span>
        </div>
        <div v-if="testResult.response" class="tr-response">
          模型回复：{{ testResult.response }}
        </div>
        <div v-if="testResult.error" class="tr-error">
          错误：{{ testResult.error }}
        </div>
      </div>

      <!-- 当前生效配置 -->
      <div v-if="llmStatus.provider" class="current-config">
        <div class="cc-title">当前生效配置</div>
        <div class="cc-row">
          <span class="cc-label">提供商</span>
          <el-tag size="small" type="info">{{ llmStatus.provider }}</el-tag>
        </div>
        <div class="cc-row">
          <span class="cc-label">模型</span>
          <span class="cc-value">{{ llmStatus.model || '—' }}</span>
        </div>
        <div class="cc-row">
          <span class="cc-label">API 地址</span>
          <span class="cc-value">{{ llmStatus.base_url || '—' }}</span>
        </div>
        <div class="cc-row">
          <span class="cc-label">API Key</span>
          <span class="cc-value">{{ llmStatus.api_key_preview || '未设置' }}</span>
        </div>
        <!-- 配置不一致警告 -->
        <div v-if="configMismatch" class="config-warning">
          ⚠️ 检测到配置不一致：表单中的 API 地址与当前生效地址不同，请重新保存。
        </div>
      </div>
    </div>

    <!-- 飞书配置 -->
    <div class="settings-card">
      <div class="card-header">
        <span class="card-title">🔔 飞书机器人</span>
        <el-tag :type="health.feishu_configured ? 'success' : 'warning'" size="small" effect="dark">
          {{ health.feishu_configured ? '✓ 已配置' : '未配置' }}
        </el-tag>
      </div>

      <div class="config-guide">
        <p>飞书机器人 Webhook 需要在 <code>.env</code> 文件中配置（暂不支持前端修改）：</p>
        <ol>
          <li>在飞书群中点击右上角「设置」→「群机器人」→「添加机器人」</li>
          <li>选择「自定义机器人」，复制 Webhook 地址</li>
          <li>在项目根目录 <code>.env</code> 文件中设置：</li>
        </ol>
        <pre>QUANT_FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/你的token</pre>
      </div>

      <div class="card-actions">
        <el-button type="primary" :loading="testingFeishu" @click="testFeishu">
          📲 发送测试消息
        </el-button>
        <span v-if="feishuResult" style="margin-left:12px;font-size:13px"
          :class="feishuResult.ok ? 'text-ok' : 'text-fail'">
          {{ feishuResult.msg }}
        </span>
      </div>
    </div>

    <!-- 系统状态 -->
    <div class="settings-card">
      <div class="card-header">
        <span class="card-title">📊 系统状态</span>
        <el-button size="small" :icon="Refresh" @click="loadStatus" circle plain />
      </div>

      <div class="status-grid">
        <div class="status-item">
          <div class="si-label">数据源</div>
          <el-tag type="info" size="small">{{ health.market_provider }}</el-tag>
        </div>
        <div class="status-item">
          <div class="si-label">WebSocket</div>
          <el-tag :type="wsStatus.loop_running ? 'success' : 'danger'" size="small">
            {{ wsStatus.loop_running ? '运行中' : '未启动' }}
          </el-tag>
        </div>
        <div class="status-item">
          <div class="si-label">行情订阅</div>
          <span class="si-value">{{ wsStatus.quotes_clients }} 个客户端</span>
        </div>
        <div class="status-item">
          <div class="si-label">提醒订阅</div>
          <span class="si-value">{{ wsStatus.alerts_clients }} 个客户端</span>
        </div>
        <div class="status-item">
          <div class="si-label">LLM 状态</div>
          <el-tag :type="health.llm_configured ? 'success' : 'danger'" size="small">
            {{ health.llm_configured ? '已配置' : '未配置' }}
          </el-tag>
        </div>
        <div class="status-item">
          <div class="si-label">飞书状态</div>
          <el-tag :type="health.feishu_configured ? 'success' : 'warning'" size="small">
            {{ health.feishu_configured ? '已配置' : '未配置' }}
          </el-tag>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
defineOptions({ name: 'Settings' })
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { api, http } from '../api.js'

const health = ref({ llm_configured: false, feishu_configured: false, market_provider: 'akshare' })
const wsStatus = ref({ loop_running: false, quotes_clients: 0, alerts_clients: 0 })
const llmStatus = ref({})
const presets = ref({})

const saving = ref(false)
const testing = ref(false)
const testingFeishu = ref(false)
const testResult = ref(null)
const feishuResult = ref(null)

const llmForm = ref({
  provider: 'deepseek',
  api_key: '',
  base_url: 'https://api.deepseek.com/v1',
  model: 'deepseek-chat',
  temperature: 0.3,
  timeout: 120,
})

const currentPreset = computed(() => presets.value[llmForm.value.provider] || null)

// 检测表单配置与生效配置是否一致
const configMismatch = computed(() => {
  if (!llmStatus.value.base_url) return false
  const formUrl = llmForm.value.base_url?.replace(/\/chat\/completions\/?$/, '').replace(/\/$/, '')
  const activeUrl = llmStatus.value.base_url?.replace(/\/$/, '')
  return formUrl && activeUrl && formUrl !== activeUrl
})

function applyPreset(key) {
  const preset = presets.value[key]
  if (!preset) return
  llmForm.value.provider = key
  // 强制覆盖 API 地址和模型名
  if (preset.base_url) llmForm.value.base_url = preset.base_url
  if (preset.default_model) llmForm.value.model = preset.default_model
  // 清空 api_key，提示用户重新填
  llmForm.value.api_key = ''
}

async function loadStatus() {
  try {
    const [h, ws, llm] = await Promise.all([
      api.health(),
      api.wsStatus(),
      api.llmConfig(),
    ])
    health.value = h
    wsStatus.value = ws
    llmStatus.value = llm.effective || {}
    presets.value = llm.presets || {}

    // 用当前生效配置填充表单（api_key 不回填，保持空）
    const eff = llm.effective || {}
    if (eff.provider) llmForm.value.provider = eff.provider
    if (eff.base_url) llmForm.value.base_url = eff.base_url
    if (eff.model) llmForm.value.model = eff.model
    if (eff.temperature != null) llmForm.value.temperature = eff.temperature
    if (eff.timeout) llmForm.value.timeout = eff.timeout
    // api_key 不回填（安全考虑），只显示 preview
  } catch (e) {
    console.error(e)
  }
}

async function saveLLMConfig() {
  if (!llmForm.value.api_key && llmForm.value.provider !== 'keyword' && llmForm.value.provider !== 'ollama') {
    ElMessage.warning('请填写 API Key')
    return
  }
  saving.value = true
  testResult.value = null
  try {
    const payload = {
      provider: llmForm.value.provider,
      // 自动去掉末尾的 /chat/completions（常见填写错误）
      base_url: llmForm.value.base_url.replace(/\/chat\/completions\/?$/, '').replace(/\/$/, ''),
      model: llmForm.value.model,
      temperature: llmForm.value.temperature,
      timeout: llmForm.value.timeout,
    }
    // 只有填了 api_key 才更新（避免覆盖已有的）
    if (llmForm.value.api_key) {
      payload.api_key = llmForm.value.api_key
    }
    const result = await api.llmConfigSet(payload)
    llmStatus.value = result.effective || {}
    health.value.llm_configured = result.effective?.is_llm_available || false
    ElMessage.success('配置已保存，立即生效（无需重启）')
    llmForm.value.api_key = ''  // 清空 key 输入框
  } catch (e) {
    ElMessage.error('保存失败：' + e.message)
  } finally {
    saving.value = false
  }
}

async function testLLM() {
  testing.value = true
  testResult.value = null
  try {
    const result = await api.llmTest('quick')
    const chatTest = result.tests?.chat || {}
    testResult.value = {
      ok: chatTest.ok,
      duration_ms: chatTest.duration_ms,
      response: chatTest.response,
      error: chatTest.error,
    }
    if (chatTest.ok) {
      ElMessage.success('连接成功！')
    } else {
      ElMessage.error('连接失败：' + (chatTest.error || '未知错误'))
    }
  } catch (e) {
    testResult.value = { ok: false, error: e.message }
    ElMessage.error('测试失败：' + e.message)
  } finally {
    testing.value = false
  }
}

async function resetLLMConfig() {
  try {
    await api.llmConfigReset()
    ElMessage.success('已重置为默认配置')
    await loadStatus()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function testFeishu() {
  testingFeishu.value = true
  feishuResult.value = null
  try {
    await http.post('/notify/test', { title: '测试消息', content: '飞书机器人配置成功！来自 AlphaAgent。' })
    feishuResult.value = { ok: true, msg: '✓ 发送成功' }
  } catch (e) {
    feishuResult.value = { ok: false, msg: '✗ 发送失败：' + e.message }
  } finally {
    testingFeishu.value = false
  }
}

onMounted(loadStatus)
</script>

<style scoped>
.settings-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
  max-width: 760px;
}

.settings-page h2 { font-size: 20px; font-weight: 700; }

.settings-card {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 10px;
  padding: 20px 24px;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 18px;
}

.card-title {
  font-size: 15px;
  font-weight: 600;
  color: #e0e0e0;
  flex: 1;
}

/* 预设按钮行 */
.preset-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.field-label {
  font-size: 13px;
  color: #909399;
  white-space: nowrap;
  min-width: 60px;
}

.preset-btns { display: flex; gap: 6px; flex-wrap: wrap; }

/* 表单提示 */
.field-hint {
  font-size: 11px;
  color: #606266;
  margin-top: 4px;
  line-height: 1.5;
}

/* 操作按钮 */
.card-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 16px;
  flex-wrap: wrap;
}

/* 测试结果 */
.test-result {
  margin-top: 14px;
  padding: 12px 14px;
  border-radius: 6px;
  font-size: 13px;
}

.test-ok {
  background: rgba(103, 194, 58, 0.1);
  border: 1px solid rgba(103, 194, 58, 0.3);
}

.test-fail {
  background: rgba(245, 108, 108, 0.1);
  border: 1px solid rgba(245, 108, 108, 0.3);
}

.tr-header { font-weight: 600; margin-bottom: 4px; }
.tr-response { color: #c0c4cc; margin-top: 4px; }
.tr-error { color: #f56c6c; margin-top: 4px; }

/* 当前生效配置 */
.current-config {
  margin-top: 16px;
  padding: 12px 14px;
  background: #16162a;
  border: 1px solid #2a2a4a;
  border-radius: 6px;
}

.cc-title {
  font-size: 11px;
  color: #606266;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 8px;
}

.cc-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 3px 0;
  font-size: 13px;
}

.cc-label {
  color: #606266;
  min-width: 70px;
  font-size: 12px;
}

.cc-value { color: #c0c4cc; font-family: monospace; font-size: 12px; }

.config-warning {
  margin-top: 10px;
  padding: 8px 10px;
  background: rgba(230, 162, 60, 0.1);
  border: 1px solid rgba(230, 162, 60, 0.4);
  border-radius: 4px;
  font-size: 12px;
  color: #e6a23c;
}

/* 飞书配置说明 */
.config-guide {
  font-size: 13px;
  line-height: 1.8;
  color: #c0c4cc;
  margin-bottom: 14px;
}

.config-guide ol { padding-left: 20px; margin: 8px 0; }
.config-guide li { margin-bottom: 4px; }

.config-guide pre {
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
  border-radius: 6px;
  padding: 10px 12px;
  font-size: 12px;
  color: #a0cfff;
  overflow-x: auto;
  white-space: pre-wrap;
  margin-top: 8px;
}

.config-guide code {
  background: #0f0f1a;
  padding: 2px 5px;
  border-radius: 3px;
  color: #a0cfff;
  font-size: 12px;
}

/* 系统状态网格 */
.status-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.status-item {
  background: #16162a;
  border: 1px solid #2a2a4a;
  border-radius: 6px;
  padding: 10px 12px;
}

.si-label {
  font-size: 11px;
  color: #606266;
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.si-value { font-size: 13px; color: #c0c4cc; }

.text-ok { color: #67c23a; }
.text-fail { color: #f56c6c; }
</style>
