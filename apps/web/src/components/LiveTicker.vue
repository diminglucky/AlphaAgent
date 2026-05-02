<template>
  <div class="ticker-bar">
    <div class="ticker-status">
      <span class="dot" :class="{ live: connected }"></span>
      <span>{{ connected ? '实时行情' : '连接中…' }}</span>
    </div>
    <div class="ticker-list">
      <div v-for="q in items" :key="q.symbol" class="ticker-item">
        <span class="sym">{{ q.symbol }}</span>
        <span class="price" :class="q.change >= 0 ? 'up' : 'down'">
          {{ q.last_price.toFixed(2) }}
        </span>
        <span class="change" :class="q.change >= 0 ? 'up' : 'down'">
          {{ q.change >= 0 ? '+' : '' }}{{ q.change_pct.toFixed(2) }}%
        </span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { openQuoteStream } from '../api.js'

const items = ref([])
const connected = ref(false)
let close = null

onMounted(() => {
  close = openQuoteStream((msg) => {
    if (msg.type === 'quotes') {
      items.value = msg.data
      connected.value = true
    }
  })
})

onUnmounted(() => close?.())
</script>

<style scoped>
.ticker-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  background: #1f1f1f;
  color: #fff;
  padding: 8px 16px;
  border-radius: 6px;
  overflow: hidden;
  margin-bottom: 16px;
}
.ticker-status {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  white-space: nowrap;
  color: #ddd;
  border-right: 1px solid #444;
  padding-right: 16px;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #999;
}
.dot.live {
  background: #52c41a;
  box-shadow: 0 0 6px #52c41a;
  animation: pulse 1.5s infinite;
}
@keyframes pulse {
  0% { opacity: 1; }
  50% { opacity: 0.4; }
  100% { opacity: 1; }
}
.ticker-list {
  display: flex;
  gap: 24px;
  overflow-x: auto;
  flex: 1;
}
.ticker-list::-webkit-scrollbar { display: none; }
.ticker-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  white-space: nowrap;
}
.sym { color: #aaa; }
.price { font-weight: 600; }
.change { font-size: 12px; }
.up { color: #ff6b6b; }
.down { color: #51cf66; }
</style>
