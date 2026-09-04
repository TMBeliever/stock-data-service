<script setup lang="ts">
import { ref } from 'vue'
import EChartWrapper from '@/components/EChartWrapper.vue'

// 基础演示图表配置 (保持暗黑质感与图表插槽就绪)
const chartOption = ref<Record<string, any>>({
  backgroundColor: 'transparent',
  grid: { left: 45, right: 20, top: 30, bottom: 30 },
  tooltip: { trigger: 'axis' },
  xAxis: {
    type: 'category',
    data: ['周一', '周二', '周三', '周四', '周五'],
    axisLabel: { color: 'rgba(255,255,255,0.45)', fontSize: 11 },
    axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } },
  },
  yAxis: {
    type: 'value',
    scale: true,
    axisLabel: { color: 'rgba(255,255,255,0.45)', fontSize: 11 },
    splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
  },
  series: [
    {
      name: '核心指数走势',
      type: 'line',
      smooth: true,
      data: [3850, 3880, 3865, 3910, 3935],
      lineStyle: { width: 2.2, color: '#ff2d55' },
      areaStyle: {
        color: {
          type: 'linear',
          x: 0,
          y: 0,
          x2: 0,
          y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(255, 45, 85, 0.25)' },
            { offset: 1, color: 'rgba(255, 45, 85, 0.0)' },
          ],
        },
      },
    },
  ],
})

const statCards = ref([
  { title: '核心宽基', value: '3,935.20', change: '+1.24%', isUp: true, desc: '主指数实时走势' },
  { title: '全市场量化池', value: '5,340 只', change: '在线', isUp: true, desc: '实时数据流监控' },
  { title: '策略回测中枢', value: '就绪', change: 'v0.1.0', isUp: true, desc: '内核服务运行中' },
  { title: 'API 网关状态', value: 'Active', change: '8080/8000', isUp: true, desc: '底层端点已对齐' },
])
</script>

<template>
  <div class="space-y-6">
    <!-- 1. 首页头部面板 -->
    <div class="glass-panel p-6">
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div class="flex items-center space-x-2.5">
            <span class="text-2xl">📈</span>
            <h1 class="text-xl font-bold text-white tracking-tight">量化投研中枢 (QuantScope)</h1>
          </div>
          <p class="text-xs text-zinc-400 mt-1.5">
            全栈量化系统前端框架已就绪，保留 Raycast Institutional Dark 视觉设计系统与布局容器，可在此构建您的全新功能。
          </p>
        </div>
        <div class="flex items-center space-x-2">
          <span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-mono">
            <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse-glow"></span>
            系统就绪
          </span>
        </div>
      </div>

      <!-- 核心指标卡片 -->
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mt-6">
        <div
          v-for="(c, idx) in statCards"
          :key="idx"
          class="p-4 rounded-xl bg-white/[0.02] border border-white/[0.06] hover:border-white/[0.12] transition-all"
        >
          <div class="flex items-center justify-between text-xs text-zinc-400 mb-1">
            <span>{{ c.title }}</span>
            <span :class="c.isUp ? 'text-red-400' : 'text-emerald-400'" class="font-mono font-bold text-[11px]">
              {{ c.change }}
            </span>
          </div>
          <div class="text-lg font-bold font-mono text-white tracking-tight">{{ c.value }}</div>
          <div class="text-[10px] text-zinc-500 mt-1 font-mono">{{ c.desc }}</div>
        </div>
      </div>
    </div>

    <!-- 2. 主可视化图表容器 -->
    <div class="glass-panel p-6 space-y-4">
      <div class="flex items-center justify-between pb-3 border-b border-white/[0.08]">
        <div class="flex items-center space-x-2">
          <span class="text-base">📊</span>
          <h2 class="text-sm font-bold text-white">核心走势 / 可视化画板</h2>
        </div>
        <div class="flex items-center space-x-2">
          <span class="kbd-badge text-[10px]">ECharts 5.6</span>
          <span class="text-zinc-500 text-xs font-mono">自适应容器</span>
        </div>
      </div>
      <div class="w-full">
        <EChartWrapper :option="chartOption" height="360px" />
      </div>
    </div>

    <!-- 3. 预留功能卡片插槽区 -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
      <div class="glass-panel p-5 space-y-3">
        <div class="flex items-center justify-between pb-2 border-b border-white/[0.06]">
          <h3 class="text-xs font-bold text-zinc-200">功能模块容器 A</h3>
          <span class="text-[10px] text-zinc-500 font-mono">SLOT_A</span>
        </div>
        <div class="h-44 flex flex-col items-center justify-center border border-dashed border-white/[0.08] rounded-xl text-xs text-zinc-500 space-y-1">
          <span>待开发业务面板</span>
          <span class="text-[10px] text-zinc-600 font-mono">可放置数据表格、漏斗选股或策略参数</span>
        </div>
      </div>

      <div class="glass-panel p-5 space-y-3">
        <div class="flex items-center justify-between pb-2 border-b border-white/[0.06]">
          <h3 class="text-xs font-bold text-zinc-200">功能模块容器 B</h3>
          <span class="text-[10px] text-zinc-500 font-mono">SLOT_B</span>
        </div>
        <div class="h-44 flex flex-col items-center justify-center border border-dashed border-white/[0.08] rounded-xl text-xs text-zinc-500 space-y-1">
          <span>待开发业务面板</span>
          <span class="text-[10px] text-zinc-600 font-mono">可放置行情分时、财务杜邦分析或交易流水</span>
        </div>
      </div>
    </div>
  </div>
</template>
