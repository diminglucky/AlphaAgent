<template>
  <div class="settings-page">
    <h2>系统设置</h2>

    <div class="settings-card readiness-card">
      <div class="card-header">
        <span class="card-title">🧭 可用性检查</span>
        <el-tag :type="readinessStatusType" size="small" effect="dark">
          {{ readinessStatusLabel }}
        </el-tag>
      </div>
      <div class="readiness-summary">
        <div class="readiness-tile">
          <span>本地 / 模拟盘</span>
          <b :class="readiness?.local_ready ? 'text-ok' : 'text-fail'">
            {{ readiness ? (readiness.local_ready ? '可用' : '阻断') : '检查中' }}
          </b>
        </div>
        <div class="readiness-tile">
          <span>QMT 实盘</span>
          <b :class="readiness?.live_trading_ready ? 'text-ok' : 'text-fail'">
            {{ readiness ? (readiness.live_trading_ready ? '可用' : '不可用') : '检查中' }}
          </b>
        </div>
        <div class="readiness-tile wide">
          <span>下一步</span>
          <b>{{ readiness?.summary?.next_action || '加载中...' }}</b>
        </div>
      </div>
      <div v-if="readinessChecks.length" class="readiness-checks">
        <div
          v-for="item in readinessChecks"
          :key="item.id"
          class="readiness-check"
          :class="`readiness-${item.status}`"
        >
          <div class="rc-top">
            <span>{{ item.label }}</span>
            <el-tag size="small" :type="checkTagType(item.status)">
              {{ checkLabel(item.status) }}
            </el-tag>
          </div>
          <div class="rc-message">{{ item.message }}</div>
          <div v-if="item.next_action" class="rc-action">下一步：{{ item.next_action }}</div>
        </div>
      </div>
    </div>

    <div class="settings-card">
      <div class="card-header">
        <span class="card-title">🔐 API 鉴权</span>
        <el-tag :type="apiKeyConfigured ? 'success' : 'info'" size="small" effect="dark">
          {{ apiKeyConfigured ? '已保存' : '未设置' }}
        </el-tag>
      </div>
      <el-form label-width="100px">
        <el-form-item label="X-Api-Key">
          <el-input
            v-model="apiKeyInput"
            type="password"
            show-password
            placeholder="生产环境开启 QUANT_AUTH_ENABLED 后填写"
            clearable
          />
          <div class="field-hint">这是平台 API 鉴权 Key，不是大模型 API Key。保存后所有请求会自动带上该请求头。</div>
        </el-form-item>
      </el-form>
      <div class="card-actions">
        <el-button type="primary" @click="saveApiKey">保存 API Key</el-button>
        <el-button plain @click="clearApiKey">清除</el-button>
      </div>
    </div>

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
        <p>飞书机器人 Webhook 支持运行时保存，立即生效且不需要重启服务：</p>
        <ol>
          <li>在飞书群中点击右上角「设置」→「群机器人」→「添加机器人」</li>
          <li>选择「自定义机器人」，复制 Webhook 地址</li>
          <li>粘贴到下面输入框保存。生产环境也可以继续使用 <code>QUANT_FEISHU_WEBHOOK_URL</code> 作为默认值。</li>
        </ol>
      </div>

      <el-form label-width="100px">
        <el-form-item label="Webhook">
          <el-input
            v-model="feishuForm.webhook_url"
            type="password"
            show-password
            placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..."
            clearable
          />
          <div class="field-hint">
            当前来源：{{ feishuConfig.source || 'none' }}；当前值：{{ feishuConfig.webhook_url_preview || '未设置' }}
          </div>
        </el-form-item>
      </el-form>

      <div class="card-actions">
        <el-button type="primary" :loading="savingFeishu" @click="saveFeishuConfig">
          保存飞书配置
        </el-button>
        <el-button plain :loading="savingFeishu" @click="resetFeishuConfig">
          重置为环境变量
        </el-button>
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
          <div class="si-label">API 鉴权</div>
          <el-tag :type="authStatusType" size="small">
            {{ authStatusLabel }}
          </el-tag>
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
import { api, getApiKey, setApiKey } from '../api.js'

const health = ref({
  llm_configured: false,
  feishu_configured: false,
  market_provider: 'akshare',
  auth_enabled: false,
  auth_configured: true,
})
const readiness = ref(null)
const wsStatus = ref({ loop_running: false, quotes_clients: 0, alerts_clients: 0 })
const llmStatus = ref({})
const presets = ref({})

const saving = ref(false)
const testing = ref(false)
const testingFeishu = ref(false)
const savingFeishu = ref(false)
const testResult = ref(null)
const feishuResult = ref(null)
const apiKeyInput = ref(getApiKey())
const apiKeyConfigured = ref(Boolean(apiKeyInput.value))
const feishuConfig = ref({})
const feishuForm = ref({ webhook_url: '' })

const llmForm = ref({
  provider: 'deepseek',
  api_key: '',
  base_url: 'https://api.deepseek.com/v1',
  model: 'deepseek-chat',
  temperature: 0.3,
  timeout: 120,
})

const currentPreset = computed(() => presets.value[llmForm.value.provider] || null)
const authStatusType = computed(() => {
  if (!health.value.auth_enabled) return 'warning'
  return health.value.auth_configured ? 'success' : 'danger'
})
const authStatusLabel = computed(() => {
  if (!health.value.auth_enabled) return '本地关闭'
  return health.value.auth_configured ? '已开启' : '缺少 Key'
})
const readinessChecks = computed(() => readiness.value?.checks || [])
const readinessStatusType = computed(() => {
  if (!readiness.value) return 'info'
  if (readiness.value.live_trading_ready) return 'success'
  if (readiness.value.local_ready) return 'warning'
  return 'danger'
})
const readinessStatusLabel = computed(() => {
  if (!readiness.value) return '检查中'
  if (readiness.value.live_trading_ready) return '实盘可用'
  if (readiness.value.local_ready) return '仅本地可用'
  return '存在阻断'
})

function saveApiKey() {
  setApiKey(apiKeyInput.value)
  apiKeyConfigured.value = Boolean(apiKeyInput.value?.trim())
  ElMessage.success('API Key 已保存')
}

function clearApiKey() {
  apiKeyInput.value = ''
  setApiKey('')
  apiKeyConfigured.value = false
  ElMessage.success('API Key 已清除')
}

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
    const [h, r] = await Promise.all([
      api.health(),
      api.readiness().catch(() => null),
    ])
    health.value = h
    readiness.value = r
    const [wsResult, llmResult, notifyResult] = await Promise.allSettled([
      api.wsStatus(),
      api.llmConfig(),
      api.notifyConfig(),
    ])
    if (wsResult.status === 'fulfilled') wsStatus.value = wsResult.value

    const llm = llmResult.status === 'fulfilled' ? llmResult.value : null
    if (llm) {
      llmStatus.value = llm.effective || {}
      presets.value = llm.presets || {}
    }

    const notifyCfg = notifyResult.status === 'fulfilled' ? notifyResult.value : null
    if (notifyCfg) feishuConfig.value = notifyCfg.feishu || {}

    // 用当前生效配置填充表单（api_key 不回填，保持空）
    const eff = llm?.effective || {}
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

function checkTagType(status) {
  if (status === 'pass') return 'success'
  if (status === 'warn') return 'warning'
  return 'danger'
}

function checkLabel(status) {
  if (status === 'pass') return '通过'
  if (status === 'warn') return '注意'
  return '阻断'
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
    await api.notifyTest({ title: '测试消息', content: '飞书机器人配置成功！来自 AlphaAgent。' })
    feishuResult.value = { ok: true, msg: '✓ 发送成功' }
  } catch (e) {
    feishuResult.value = { ok: false, msg: '✗ 发送失败：' + e.message }
  } finally {
    testingFeishu.value = false
  }
}

async function saveFeishuConfig() {
  if (!feishuForm.value.webhook_url?.trim()) {
    ElMessage.warning('请填写飞书 Webhook URL')
    return
  }
  savingFeishu.value = true
  try {
    const result = await api.notifyConfigSet({ webhook_url: feishuForm.value.webhook_url.trim() })
    feishuConfig.value = result.feishu || {}
    health.value.feishu_configured = Boolean(feishuConfig.value.configured)
    feishuForm.value.webhook_url = ''
    ElMessage.success('飞书配置已保存，立即生效')
  } catch (e) {
    ElMessage.error('保存飞书配置失败：' + e.message)
  } finally {
    savingFeishu.value = false
  }
}

async function resetFeishuConfig() {
  savingFeishu.value = true
  try {
    const result = await api.notifyConfigReset()
    feishuConfig.value = result.feishu || {}
    health.value.feishu_configured = Boolean(feishuConfig.value.configured)
    feishuForm.value.webhook_url = ''
    ElMessage.success('已重置为环境变量配置')
  } catch (e) {
    ElMessage.error('重置失败：' + e.message)
  } finally {
    savingFeishu.value = false
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

.readiness-card {
  border-color: rgba(64, 158, 255, 0.28);
  background:
    radial-gradient(circle at top right, rgba(64, 158, 255, 0.14), transparent 32%),
    #1a1a2e;
}

.readiness-summary {
  display: grid;
  grid-template-columns: 150px 150px 1fr;
  gap: 12px;
  margin-bottom: 14px;
}

.readiness-tile {
  background: #16162a;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  padding: 12px 14px;
}

.readiness-tile span {
  display: block;
  color: #909399;
  font-size: 12px;
  margin-bottom: 6px;
}

.readiness-tile b {
  display: block;
  color: #d7dce7;
  font-size: 13px;
  line-height: 1.5;
}

.readiness-checks {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.readiness-check {
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  padding: 12px;
  background: #141426;
}

.readiness-pass { border-color: rgba(103, 194, 58, 0.35); }
.readiness-warn { border-color: rgba(230, 162, 60, 0.42); }
.readiness-fail { border-color: rgba(245, 108, 108, 0.48); }

.rc-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
  color: #e0e0e0;
  font-weight: 600;
}

.rc-message,
.rc-action {
  color: #c0c4cc;
  font-size: 12px;
  line-height: 1.6;
}

.rc-action {
  color: #f3d19e;
  margin-top: 6px;
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

@media (max-width: 900px) {
  .readiness-summary { grid-template-columns: 1fr; }
  .readiness-checks { grid-template-columns: 1fr; }
}
</style>
