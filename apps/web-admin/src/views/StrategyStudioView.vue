<script setup lang="ts">
import CodeEditorPanel from '@/components/strategy/CodeEditorPanel.vue'
</script>

<template>
  <div class="h-[calc(100vh-7rem)] w-full min-h-0 overflow-hidden">
    <!-- 沉浸式宽屏量化策略代码工作台 (主导视口，回测由全站悬浮工作舱 ⌘B 随时弹出) -->
    <div class="w-full h-full">
      <CodeEditorPanel />
    </div>
  </div>
</template>
