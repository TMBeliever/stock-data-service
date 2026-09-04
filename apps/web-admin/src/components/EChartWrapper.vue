<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts'

const props = withDefaults(
  defineProps<{
    option: Record<string, any>
    height?: string
    loading?: boolean
  }>(),
  {
    height: '320px',
    loading: false,
  }
)

const chartContainer = ref<HTMLDivElement | null>(null)
let chartInstance: echarts.ECharts | null = null
let resizeObserver: ResizeObserver | null = null

function initChart() {
  if (!chartContainer.value) return
  if (chartInstance) {
    chartInstance.dispose()
    chartInstance = null
  }
  chartInstance = echarts.init(chartContainer.value, 'dark', {
    renderer: 'canvas',
  })
  if (props.option && Object.keys(props.option).length > 0) {
    chartInstance.setOption({
      backgroundColor: 'transparent',
      ...props.option,
    })
  }
  requestAnimationFrame(() => {
    chartInstance?.resize()
  })
}

watch(
  () => props.option,
  (newOpt) => {
    if (!chartInstance && chartContainer.value) {
      initChart()
      return
    }
    if (chartInstance && newOpt && Object.keys(newOpt).length > 0) {
      chartInstance.clear()
      chartInstance.setOption(
        {
          backgroundColor: 'transparent',
          ...newOpt,
        },
        true
      )
      requestAnimationFrame(() => {
        chartInstance?.resize()
      })
    }
  },
  { deep: true }
)

watch(
  () => props.loading,
  (isLoading) => {
    if (!chartInstance) return
    if (isLoading) {
      chartInstance.showLoading({
        text: '加载中...',
        color: '#ff2d55',
        textColor: '#a1a1aa',
        maskColor: 'rgba(10, 10, 12, 0.6)',
      })
    } else {
      chartInstance.hideLoading()
    }
  }
)

function onResize() {
  chartInstance?.resize()
}

onMounted(() => {
  initChart()
  window.addEventListener('resize', onResize)
  if (chartContainer.value && window.ResizeObserver) {
    resizeObserver = new ResizeObserver(() => {
      chartInstance?.resize()
    })
    resizeObserver.observe(chartContainer.value)
  }
})

onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  if (resizeObserver) {
    resizeObserver.disconnect()
    resizeObserver = null
  }
  chartInstance?.dispose()
  chartInstance = null
})
</script>

<template>
  <div ref="chartContainer" class="w-full" :style="{ height: props.height }"></div>
</template>
