<template>
  <div>
    <el-card shadow="never" style="border-radius:8px; margin-bottom:20px">
      <template #header>
        <span style="font-weight:600">📑 交易日报</span>
        <span style="float:right">
          <el-button size="small" @click="load">🔄 刷新</el-button>
          <el-button size="small" type="primary" @click="downloadMd">⬇ 下载 Markdown</el-button>
          <el-button size="small" @click="copyText">📋 复制</el-button>
        </span>
      </template>
      <p style="color:#888; font-size:13px; margin:0">
        每次刷新会基于当前持仓 / Agent 决策 / 信号 / 风控事件 / 新闻 重新生成日报。可下载用于存档或分享。
      </p>
    </el-card>

    <el-card shadow="never" style="border-radius:8px" v-loading="loading">
      <div v-if="rendered" v-html="rendered" class="md-render"></div>
      <el-empty v-else-if="!loading" description="点击刷新生成报告" :image-size="80" />
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { http } from '../api.js'

const raw = ref('')
const rendered = ref('')
const loading = ref(false)

const escapeHtml = (s) => s.replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))

// minimal markdown → html (headings, bold, list, table, hr, em)
const renderMd = (md) => {
  const lines = md.split('\n')
  let html = ''
  let inTable = false
  for (let i = 0; i < lines.length; i++) {
    let l = lines[i]
    // table block
    if (/^\|.*\|/.test(l)) {
      if (!inTable) { html += '<table class="md-table"><tbody>'; inTable = true }
      const cells = l.split('|').slice(1, -1).map(c => c.trim())
      // skip separator row
      if (cells.every(c => /^[-:]+$/.test(c))) continue
      const tag = (i === 0 || /^\|/.test(lines[i - 1] || '') === false) ? 'th' : 'td'
      html += '<tr>' + cells.map(c => `<${tag}>${formatInline(c)}</${tag}>`).join('') + '</tr>'
      continue
    } else if (inTable) {
      html += '</tbody></table>'
      inTable = false
    }
    if (/^# /.test(l)) html += `<h1>${formatInline(l.slice(2))}</h1>`
    else if (/^## /.test(l)) html += `<h2>${formatInline(l.slice(3))}</h2>`
    else if (/^### /.test(l)) html += `<h3>${formatInline(l.slice(4))}</h3>`
    else if (/^- /.test(l)) html += `<li>${formatInline(l.slice(2))}</li>`
    else if (/^---/.test(l)) html += '<hr>'
    else if (l.trim() === '') html += '<br>'
    else html += `<p>${formatInline(l)}</p>`
  }
  if (inTable) html += '</tbody></table>'
  // wrap consecutive <li> into <ul>
  html = html.replace(/(<li>[\s\S]*?<\/li>)(?!<li>)/g, '<ul>$1</ul>')
  return html
}

const formatInline = (s) => {
  let h = escapeHtml(s)
  h = h.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  h = h.replace(/\*(.+?)\*/g, '<em>$1</em>')
  h = h.replace(/_(.+?)_/g, '<em>$1</em>')
  return h
}

const load = async () => {
  loading.value = true
  try {
    const res = await http.get('/reports/daily', { responseType: 'text', transformResponse: [(d) => d] })
    raw.value = typeof res === 'string' ? res : res.toString()
    rendered.value = renderMd(raw.value)
  } catch (e) {
    ElMessage.error('生成报告失败：' + e.message)
  } finally {
    loading.value = false
  }
}

const downloadMd = () => {
  const blob = new Blob([raw.value], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `quant-daily-${new Date().toISOString().slice(0, 10)}.md`
  a.click()
  URL.revokeObjectURL(url)
}

const copyText = async () => {
  try {
    await navigator.clipboard.writeText(raw.value)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.warning('复制失败，请手动选择')
  }
}

onMounted(load)
</script>

<style scoped>
.md-render {
  font-size: 14px;
  line-height: 1.7;
  color: #333;
}
.md-render :deep(h1) { font-size: 22px; margin: 16px 0 12px; border-bottom: 1px solid #eee; padding-bottom: 8px; }
.md-render :deep(h2) { font-size: 17px; margin: 24px 0 12px; color: #1890ff; }
.md-render :deep(h3) { font-size: 15px; margin: 16px 0 8px; }
.md-render :deep(ul) { padding-left: 24px; }
.md-render :deep(li) { margin: 4px 0; }
.md-render :deep(strong) { color: #f5222d; }
.md-render :deep(.md-table) { border-collapse: collapse; margin: 12px 0; width: 100%; }
.md-render :deep(.md-table td),
.md-render :deep(.md-table th) {
  border: 1px solid #e8e8e8;
  padding: 8px 12px;
  font-size: 13px;
}
.md-render :deep(.md-table th) { background: #fafafa; font-weight: 600; }
.md-render :deep(hr) { margin: 24px 0; border: 0; border-top: 1px dashed #d9d9d9; }
</style>
