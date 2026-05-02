<template>
  <div>
    <el-card shadow="never" style="border-radius:8px; margin-bottom:20px">
      <el-form inline>
        <el-form-item label="标的过滤">
          <el-input v-model="symbolFilter" placeholder="如 600519.SH" clearable style="width:200px" @change="load" />
        </el-form-item>
        <el-form-item>
          <el-button @click="load">查询</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-row :gutter="16">
      <el-col :span="14">
        <el-card shadow="never" style="border-radius:8px">
          <template #header><span style="font-weight:600">📰 新闻列表</span></template>
          <el-table :data="articles" v-loading="loading" size="small" stripe @row-click="selectArticle">
            <el-table-column prop="source" label="来源" width="100" />
            <el-table-column prop="title" label="标题" show-overflow-tooltip />
            <el-table-column label="标的" width="160">
              <template #default="{ row }">
                <el-tag v-for="s in (row.symbols || [])" :key="s" size="small" style="margin:2px">{{ s }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="published_at" label="时间" width="160" show-overflow-tooltip />
          </el-table>
          <el-empty v-if="!loading && articles.length === 0" description="暂无新闻" :image-size="60" />
        </el-card>
      </el-col>

      <el-col :span="10">
        <el-card shadow="never" style="border-radius:8px" v-if="selected">
          <template #header>
            <span style="font-weight:600">{{ selected.source }}</span>
          </template>
          <h3 style="margin-bottom:12px; font-size:15px; line-height:1.5">{{ selected.title }}</h3>
          <p style="font-size:13px; color:#888; margin-bottom:12px">{{ selected.published_at }}</p>
          <p v-if="selected.url" style="margin-bottom:12px">
            <a :href="selected.url" target="_blank" style="color:#1890ff">外部链接 →</a>
          </p>
          <div v-if="selected.symbols?.length" style="margin-bottom:12px">
            <strong style="font-size:13px">相关标的：</strong>
            <el-tag v-for="s in selected.symbols" :key="s" size="small" style="margin:3px">{{ s }}</el-tag>
          </div>
        </el-card>
        <el-card v-else shadow="never" style="border-radius:8px">
          <el-empty description="点击新闻查看详情" :image-size="80" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api.js'

const articles = ref([])
const loading = ref(false)
const selected = ref(null)
const symbolFilter = ref('')

const selectArticle = (row) => { selected.value = row }

const load = async () => {
  loading.value = true
  try {
    const params = { limit: 30 }
    if (symbolFilter.value) params.symbol = symbolFilter.value
    const data = await api.newsArticles(params)
    articles.value = Array.isArray(data) ? data : (data.articles ?? [])
  } catch {
    articles.value = []
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>
