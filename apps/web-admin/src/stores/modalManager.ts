import { defineStore } from 'pinia'
import { ref, computed, watch, onUnmounted, type Ref } from 'vue'

export interface ModalInstance {
  id: string
  zIndex: number
  onClose?: () => void
}

/**
 * 全局统一弹窗层级调度中枢 (Unified Modal & Z-Index Layer Manager)
 * 核心保证：后弹出的弹窗层级严格高于先弹出的弹窗，始终处于最顶层；
 * 支持点击唤醒至顶层 (bringToFront) 与 Esc 键级联关闭顶层弹窗。
 */
export const useModalManagerStore = defineStore('modalManager', () => {
  const BASE_Z_INDEX = 10000
  const STEP = 10

  // 活跃弹窗栈（栈底为先打开的弹窗，栈顶为最新打开/置顶的弹窗）
  const stack = ref<ModalInstance[]>([])

  // 当前全局最高 z-index
  const topZIndex = computed(() => {
    if (stack.value.length === 0) return BASE_Z_INDEX
    return stack.value[stack.value.length - 1].zIndex
  })

  // 获取特定弹窗当前的 z-index
  function getZIndex(id: string): number {
    const item = stack.value.find((m) => m.id === id)
    return item ? item.zIndex : BASE_Z_INDEX
  }

  // 判断某弹窗是否处于最顶层
  function isTopModal(id: string): boolean {
    if (stack.value.length === 0) return false
    return stack.value[stack.value.length - 1].id === id
  }

  /**
   * 注册并打开弹窗：
   * 分配高于当前所有弹窗的全新 z-index，入栈顶，确保在最顶层展示
   */
  function registerModal(id: string, onClose?: () => void): number {
    // 若已存在于栈中，先出栈
    const existingIndex = stack.value.findIndex((m) => m.id === id)
    if (existingIndex !== -1) {
      stack.value.splice(existingIndex, 1)
    }

    const currentTop = stack.value.length > 0 ? stack.value[stack.value.length - 1].zIndex : BASE_Z_INDEX
    const newZIndex = currentTop + STEP

    const modalItem: ModalInstance = {
      id,
      zIndex: newZIndex,
      onClose,
    }

    stack.value.push(modalItem)
    return newZIndex
  }

  /**
   * 将指定弹窗唤醒并重新置于最顶层 (例如用户点击了下层弹窗)
   */
  function bringToFront(id: string): number {
    const item = stack.value.find((m) => m.id === id)
    if (!item) return BASE_Z_INDEX
    if (isTopModal(id)) return item.zIndex

    // 移出后追加到栈顶
    stack.value = stack.value.filter((m) => m.id !== id)
    const currentTop = stack.value.length > 0 ? stack.value[stack.value.length - 1].zIndex : BASE_Z_INDEX
    item.zIndex = currentTop + STEP
    stack.value.push(item)
    return item.zIndex
  }

  /**
   * 弹窗关闭时注销
   */
  function unregisterModal(id: string) {
    stack.value = stack.value.filter((m) => m.id !== id)
  }

  /**
   * 响应全局 Esc 键：仅关闭当前处于最顶层的弹窗
   */
  function handleEscKey(): boolean {
    if (stack.value.length > 0) {
      const top = stack.value[stack.value.length - 1]
      if (top.onClose) {
        top.onClose()
      }
      unregisterModal(top.id)
      return true
    }
    return false
  }

  return {
    BASE_Z_INDEX,
    stack,
    topZIndex,
    getZIndex,
    isTopModal,
    registerModal,
    bringToFront,
    unregisterModal,
    handleEscKey,
  }
})

/**
 * 组合式 API：为单个弹窗快速接入全局层级统一调度
 */
export function useModalLayer(
  id: string,
  isOpen: Ref<boolean> | (() => boolean),
  onClose?: () => void
) {
  const modalManager = useModalManagerStore()

  const isVisible = typeof isOpen === 'function' ? computed(isOpen) : isOpen

  watch(
    isVisible,
    (val) => {
      if (val) {
        modalManager.registerModal(id, onClose)
      } else {
        modalManager.unregisterModal(id)
      }
    },
    { immediate: true }
  )

  onUnmounted(() => {
    modalManager.unregisterModal(id)
  })

  function focusModal() {
    modalManager.bringToFront(id)
  }

  const zIndex = computed(() => modalManager.getZIndex(id))

  return {
    zIndex,
    isTop: computed(() => modalManager.isTopModal(id)),
    focusModal,
  }
}
