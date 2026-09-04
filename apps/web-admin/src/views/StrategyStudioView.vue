<script setup lang="ts">
import CodeEditorPanel from '@/components/strategy/CodeEditorPanel.vue'
import BacktestDashboardPanel from '@/components/strategy/BacktestDashboardPanel.vue'
</script>

<template>
  <div class="h-[calc(100vh-7rem)] flex gap-3.5 min-h-0 overflow-hidden">
    <!-- 1. 左栏：沉浸式宽屏量化策略代码编辑器 (主导视口) -->
    <div class="flex-1 min-w-[400px] h-full transition-all duration-300">
      <CodeEditorPanel />
    </div>

    <!-- 2. 右栏：实时回测研报与历史档案看板 (舒展大屏) -->
    <div class="w-[460px] lg:w-[520px] xl:w-[580px] shrink-0 h-full transition-all duration-300">
      <BacktestDashboardPanel />
    </div>
  </div>
</template>
