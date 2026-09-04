<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'

const props = defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const router = useRouter()
const searchInput = ref<HTMLInputElement | null>(null)
const query = ref('')
const selectedIndex = ref(0)

interface CommandItem {
  id: string
  category: string
  title: string
  subtitle?: string
  badge?: string
  action: () => void
}

const commands: CommandItem[] = [
  { id: 'nav-home', category: '导航', title: '回到首页', subtitle: '回到量化投研中枢首页看板', badge: 'Home', action: () => router.push('/') },
  { id: 'act-reload', category: '操作', title: '刷新当前看板', subtitle: '重新加载页面与图表状态', badge: 'Reload', action: () => window.location.reload() },
]

const filteredCommands = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return commands
  return commands.filter(
    (c) =>
      c.title.toLowerCase().includes(q) ||
      (c.subtitle && c.subtitle.toLowerCase().includes(q)) ||
      c.category.toLowerCase().includes(q)
  )
})

watch(
  () => props.show,
  (newVal) => {
    if (newVal) {
      selectedIndex.value = 0
      query.value = ''
      nextTick(() => {
        searchInput.value?.focus()
      })
    }
  }
)

function onKeyDown(e: KeyboardEvent) {
  if (!props.show) return

  if (e.key === 'ArrowDown') {
    e.preventDefault()
    selectedIndex.value = (selectedIndex.value + 1) % Math.max(1, filteredCommands.value.length)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    selectedIndex.value =
      (selectedIndex.value - 1 + filteredCommands.value.length) % Math.max(1, filteredCommands.value.length)
  } else if (e.key === 'Enter') {
    e.preventDefault()
    const item = filteredCommands.value[selectedIndex.value]
    if (item) {
      item.action()
      emit('close')
    }
  } else if (e.key === 'Escape') {
    e.preventDefault()
    emit('close')
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKeyDown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeyDown)
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="show"
      class="fixed inset-0 z-50 flex items-start justify-center pt-24 px-4 bg-black/60 backdrop-blur-md transition-all duration-200"
      @click.self="emit('close')"
    >
      <div
        class="w-full max-w-2xl bg-[#121216]/95 border border-white/[0.12] rounded-2xl shadow-2xl shadow-black/80 overflow-hidden flex flex-col backdrop-filter backdrop-blur-2xl animate-in fade-in zoom-in-95 duration-150"
      >
        <!-- 搜索输入框 -->
        <div class="flex items-center px-4 py-3.5 border-b border-white/[0.08] relative">
          <svg class="w-5 h-5 text-zinc-400 mr-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            ref="searchInput"
            v-model="query"
            type="text"
            placeholder="搜索指令或快捷动作..."
            class="w-full bg-transparent text-sm text-white placeholder-zinc-500 focus:outline-none"
          />
          <button @click="emit('close')" class="kbd-badge cursor-pointer ml-2">ESC</button>
        </div>

        <!-- 命令结果列表 -->
        <div class="max-h-[380px] overflow-y-auto p-2 space-y-1">
          <div
            v-if="filteredCommands.length === 0"
            class="py-10 text-center text-xs text-zinc-400 flex flex-col items-center space-y-1"
          >
            <span>无匹配指令</span>
          </div>

          <div
            v-for="(item, idx) in filteredCommands"
            :key="item.id"
            @click="item.action(); emit('close')"
            @mouseenter="selectedIndex = idx"
            class="flex items-center justify-between px-3 py-2.5 rounded-xl cursor-pointer transition-all text-xs"
            :class="[
              selectedIndex === idx
                ? 'bg-white/[0.1] text-white shadow-sm'
                : 'text-zinc-300 hover:bg-white/[0.05]'
            ]"
          >
            <div class="flex items-center space-x-3 overflow-hidden">
              <span
                class="px-1.5 py-0.5 rounded text-[10px] font-medium shrink-0 bg-zinc-500/10 text-zinc-400 border border-zinc-500/20"
              >
                {{ item.category }}
              </span>
              <div class="flex flex-col truncate">
                <span class="font-medium truncate text-zinc-200">{{ item.title }}</span>
                <span v-if="item.subtitle" class="text-[11px] text-zinc-400 truncate">{{ item.subtitle }}</span>
              </div>
            </div>

            <div class="flex items-center space-x-2 shrink-0 ml-2">
              <span v-if="item.badge" class="text-[10px] text-zinc-400 font-mono">{{ item.badge }}</span>
              <span v-if="selectedIndex === idx" class="kbd-badge text-[10px]">↵ Enter</span>
            </div>
          </div>
        </div>

        <!-- 底部提示栏 -->
        <div class="px-4 py-2 border-t border-white/[0.06] bg-black/30 flex items-center justify-between text-[11px] text-zinc-500">
          <div class="flex items-center space-x-3">
            <span class="flex items-center space-x-1">
              <span class="kbd-badge text-[9px]">↑</span>
              <span class="kbd-badge text-[9px]">↓</span>
              <span>切换</span>
            </span>
            <span class="flex items-center space-x-1">
              <span class="kbd-badge text-[9px]">↵</span>
              <span>选择</span>
            </span>
          </div>
          <span class="text-zinc-500 font-mono text-[10px]">Raycast Palette</span>
        </div>
      </div>
    </div>
  </Teleport>
</template>
