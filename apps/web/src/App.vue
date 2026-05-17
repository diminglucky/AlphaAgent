<template>
  <el-container class="app-layout">
    <!-- 顶部导航 -->
    <el-header class="app-header">
      <div class="header-left">
        <span class="logo">📈 A股智能助手</span>
      </div>
      <el-menu
        mode="horizontal"
        :default-active="activeMenu"
        router
        class="nav-menu"
        background-color="#1a1a2e"
        text-color="#ccc"
        active-text-color="#409eff"
      >
        <el-menu-item index="/overview">
          <el-icon><DataAnalysis /></el-icon> 总览
        </el-menu-item>
        <el-menu-item index="/market">
          <el-icon><TrendCharts /></el-icon> 行情
        </el-menu-item>
        <el-menu-item index="/scanner">
          <el-icon><Aim /></el-icon> 潜力扫描
        </el-menu-item>
        <el-menu-item index="/agent">
          <el-icon><MagicStick /></el-icon> Agent分析
        </el-menu-item>
        <el-menu-item index="/alerts">
          <el-icon><Bell /></el-icon>
          提醒
          <el-badge v-if="unreadAlerts > 0" :value="unreadAlerts" class="alert-badge" />
        </el-menu-item>
        <el-menu-item index="/positions">
          <el-icon><Wallet /></el-icon> 持仓
        </el-menu-item>
        <el-menu-item index="/settings">
          <el-icon><Setting /></el-icon> 设置
        </el-menu-item>
      </el-menu>

      <!-- 连接状态 -->
      <div class="header-right">
        <span v-if="lastQuoteTime" style="font-size:11px;color:#606266;margin-right:6px">
          {{ lastQuoteTime }}
        </span>
        <el-tag :type="wsConnected ? 'success' : 'danger'" size="small" effect="dark">
          {{ wsConnected ? '● 实时' : '○ 连接中' }}
        </el-tag>
      </div>
    </el-header>

    <el-main class="app-main">
      <router-view v-slot="{ Component }">
        <keep-alive :include="['Overview', 'Market', 'Scanner', 'Agent', 'Alerts', 'Positions', 'Settings']">
          <component :is="Component" />
        </keep-alive>
      </router-view>
    </el-main>
  </el-container>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { TrendCharts, MagicStick, Bell, Wallet, Setting, DataAnalysis, Aim } from '@element-plus/icons-vue'
import { ElNotification } from 'element-plus'
import { openStream } from './api.js'
import { quotesMap, wsConnected, unreadAlerts, lastQuoteTime, initStreams } from './store.js'

const route = useRoute()
const activeMenu = computed(() => route.path)

onMounted(() => {
  initStreams()
})
</script>

<style>
* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background: #0f0f1a;
  color: #e0e0e0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

.app-layout { min-height: 100vh; }

.app-header {
  display: flex;
  align-items: center;
  background: #1a1a2e;
  border-bottom: 1px solid #2a2a4a;
  padding: 0 20px;
  height: 56px !important;
  gap: 16px;
}

.logo {
  font-size: 18px;
  font-weight: 700;
  color: #409eff;
  white-space: nowrap;
}

.nav-menu {
  flex: 1;
  border-bottom: none !important;
}

.nav-menu .el-menu-item {
  height: 56px;
  line-height: 56px;
}

.header-right { margin-left: auto; }

.alert-badge {
  margin-left: 4px;
  vertical-align: middle;
}

.app-main {
  background: #0f0f1a;
  padding: 20px;
  min-height: calc(100vh - 56px);
}

/* 全局暗色覆盖 */
.el-card {
  background: #1a1a2e !important;
  border-color: #2a2a4a !important;
  color: #e0e0e0 !important;
}

.el-table {
  background: #1a1a2e !important;
  color: #e0e0e0 !important;
}

.el-table th, .el-table tr {
  background: #1a1a2e !important;
}

.el-table td, .el-table th.el-table__cell {
  border-color: #2a2a4a !important;
}

.el-table--striped .el-table__body tr.el-table__row--striped td {
  background: #16162a !important;
}

.el-table__body tr:hover > td {
  background: #22224a !important;
}

.up { color: #f56c6c; }
.down { color: #67c23a; }
.flat { color: #909399; }
</style>
