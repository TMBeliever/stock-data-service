import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useStrategyStore } from '@/stores/strategy'

export interface AiToolCall {
  id: string
  name: string
  arguments?: Record<string, any>
  outputPreview?: string
  status: 'calling' | 'done' | 'failed'
  step?: number
}

export interface AgentStep {
  step: number
  thought?: string
  toolCalls: AiToolCall[]
  status: 'running' | 'done'
}

export interface AiChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  codeBlock?: string
  pageContext?: string
  toolCalls?: AiToolCall[]
  steps?: AgentStep[]
}

export interface QuickPrompt {
  label: string
  prompt: string
  icon?: string
}

export const useAiStore = defineStore('ai', () => {
  // 1. 悬浮窗显示与几何尺寸状态
  const isOpen = ref(false)
  
  // 默认位置：右侧浮动（会在挂载时根据当前 window.innerWidth 自适应初始化）
  const position = ref({
    x: typeof window !== 'undefined' ? Math.max(20, window.innerWidth - 460) : 900,
    y: 85,
  })

  // 默认尺寸：420px 宽 x 580px 高
  const size = ref({
    width: 420,
    height: 580,
  })

  // 2. 模型状态与对话记录
  const aiModel = ref<'gemini-flash-lite-latest' | 'claude'>('gemini-flash-lite-latest')
  const isStreaming = ref(false)

  const messages = ref<AiChatMessage[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content:
        '👋 你好！我是 **QuantScope 全局智能助理**。\n\n我可以根据你当前浏览的页面，提供针对性的投研辅助：\n- ⚡ **策略工作台**：自然语言写策略、排查代码漏洞、指标增强与参数调优\n- 📊 **市场大盘**：A 股宽基与行业走势剖析、估值分位数评级、宏观政策解读\n\n请随时提问，或点击下方灵感提示词开始！',
      timestamp: Date.now(),
    },
  ])

  // 辅助函数：提取 Python 代码块
  function extractPythonCode(text: string): string | null {
    const match = text.match(/```(?:python)?\s*([\s\S]*?)```/i)
    return match ? match[1].trim() : null
  }

  // 悬浮胶囊的位置（默认右下角，支持全屏自由拖动）
  const triggerPosition = ref({
    x: typeof window !== 'undefined' ? Math.max(20, window.innerWidth - 220) : 1150,
    y: typeof window !== 'undefined' ? Math.max(20, window.innerHeight - 70) : 720,
  })

  // 计算紧贴悬浮球展开的最佳视口坐标
  function calculatePositionNear(anchor?: { x: number; y: number }, capsuleW = 190, capsuleH = 44) {
    if (typeof window === 'undefined') return { x: 900, y: 85 }

    const targetAnchor = anchor || triggerPosition.value
    const screenW = window.innerWidth
    const screenH = window.innerHeight
    const winW = size.value.width
    const winH = size.value.height

    let x = targetAnchor.x
    let y = targetAnchor.y

    // 水平位置判断：
    // 若胶囊位于屏幕右半边，窗口向左对齐胶囊右边缘展开；
    // 若位于屏幕左半边，窗口与胶囊左边缘对齐展开
    if (targetAnchor.x > screenW / 2) {
      x = targetAnchor.x + capsuleW - winW
    } else {
      x = targetAnchor.x
    }

    // 垂直位置判断：
    // 若胶囊位于屏幕下半部，窗口展开在胶囊上方（留出 10px 间距）；
    // 若位于屏幕上半部，窗口展开在胶囊下方（留出 10px 间距）
    if (targetAnchor.y > screenH / 2) {
      y = targetAnchor.y - winH - 10
    } else {
      y = targetAnchor.y + capsuleH + 10
    }

    // 视口安全边缘保护，保证绝对在屏幕可见范围
    const clampedX = Math.max(12, Math.min(x, screenW - winW - 12))
    const clampedY = Math.max(20, Math.min(y, screenH - winH - 20))

    return { x: clampedX, y: clampedY }
  }

  // 3. 悬浮窗动作
  function open(anchorPos?: { x: number; y: number }) {
    if (anchorPos) {
      triggerPosition.value = { ...anchorPos }
    }
    const target = calculatePositionNear(anchorPos || triggerPosition.value)
    position.value = target
    isOpen.value = true
  }

  function toggleOpen(anchorPos?: { x: number; y: number }) {
    if (isOpen.value) {
      close()
    } else {
      open(anchorPos)
    }
  }

  function close() {
    isOpen.value = false
  }

  function updatePosition(x: number, y: number) {
    const maxX = Math.max(0, window.innerWidth - size.value.width)
    const maxY = Math.max(0, window.innerHeight - 60)
    position.value = {
      x: Math.min(Math.max(0, x), maxX),
      y: Math.min(Math.max(0, y), maxY),
    }
  }

  function updateSize(width: number, height: number) {
    size.value = {
      width: Math.max(340, Math.min(width, window.innerWidth - position.value.x)),
      height: Math.max(400, Math.min(height, window.innerHeight - position.value.y)),
    }
  }

  function updateGeometry(newX: number, newY: number, newWidth: number, newHeight: number) {
    const clampedW = Math.max(340, Math.min(newWidth, window.innerWidth - 20))
    const clampedH = Math.max(400, Math.min(newHeight, window.innerHeight - 40))
    const clampedX = Math.max(0, Math.min(newX, window.innerWidth - clampedW))
    const clampedY = Math.max(0, Math.min(newY, window.innerHeight - clampedH))
    position.value = { x: clampedX, y: clampedY }
    size.value = { width: clampedW, height: clampedH }
  }

  // 4. 根据当前页面路径获取快捷提示词
  function getQuickPromptsForRoute(routePath: string): QuickPrompt[] {
    if (routePath.startsWith('/strategy')) {
      return [
        { label: '📈 编写双均线金叉策略', prompt: '请帮我写一个双均线趋势策略，参数为快线 5 日，慢线 20 日，金叉全仓 80% 买入，死叉全仓平仓。' },
        { label: '🛡️ 添加 5% 移动止盈止损', prompt: '基于现有 BaseStrategy 规范，为当前量化策略增加动态移动止损 (Trailing Stop) 保护逻辑。' },
        { label: '💰 动态分位数估值定投', prompt: '请编写一个针对 510880 红利 ETF 的动态分位数估值定投策略，低估加倍买，高估分批主动止盈。' },
        { label: '🔍 诊断偷价与未来函数', prompt: '请帮我全面诊断当前策略代码中是否存在未来函数、偷价漏洞、滑点未覆盖或数组越界问题。' },
      ]
    } else {
      // 市场看板 / 默认页面
      return [
        { label: '📊 解读今日 A 股盘面', prompt: '请根据当前市场主要宽基指数（沪深300、中证500）与成交情况，客观解读今日盘面主力动向与多空力量对比。' },
        { label: '💎 哪些 ETF 处于低估区间', prompt: '从估值分位数与股息率角度，分析当前 A 股市场中有哪些行业或宽基 ETF 处于历史前 20% 的极度低估安全区间？' },
        { label: '📉 高位震荡防守策略', prompt: '在大盘宽基指数处于窄幅震荡且量能萎缩时，量化投资者通常采用什么样的对冲或网格套利策略来保护本金？' },
        { label: '🏦 宏观利率与降准影响', prompt: '近期国债基准收益率走势与央行货币政策变动，对于高股息红利资产和成长科技资产各自有什么传导逻辑？' },
      ]
    }
  }

  // 5. 组装情境感知的系统 Prompt
  function buildSystemPrompt(routePath: string): string {
    const strategyStore = useStrategyStore()

    if (routePath.startsWith('/strategy')) {
      let contextSnippet = `当前用户正在【量化策略投研工作台】编写与调试量化策略。
当前编辑器选中标的: ${strategyStore.symbol}
当前策略名称: ${strategyStore.activeStrategyName}
当前策略代码前 30 行预览:
\`\`\`python
${strategyStore.code.split('\n').slice(0, 30).join('\n')}
\`\`\``
      if (strategyStore.backtestResult) {
        const sum = strategyStore.backtestResult.summary
        contextSnippet += `\n最新一次回测结果快照: 累计收益率 ${(sum.total_return * 100).toFixed(2)}%, 最大回撤 -${(sum.max_drawdown * 100).toFixed(2)}%, 夏普比率 ${sum.sharpe_ratio.toFixed(2)}, 交易胜率 ${(sum.win_rate * 100).toFixed(1)}%`
      }

      return `你是一位精通 A 股与 ETF 交易的顶尖量化架构师，为 QuantScope 平台服务。
平台策略继承 BaseStrategy，核心规范：
1. 生命周期: on_bar(self, bar: Bar) 回调，bar.close, bar.open, bar.high, bar.low, bar.volume
2. 历史行情: self.context.get_closes(symbol, n), self.context.get_highs/lows/volumes
3. 内置指标直接调用: sma, ema, rsi, macd, bollinger_bands, atr
4. 调仓指令: self.order_target_percent(symbol, pct), self.close_position(symbol), self.buy, self.sell
5. 持仓获取: pos = self.get_position(symbol)
要求：
- 如果生成完整策略，请务必用 \`\`\`python ... \`\`\` 包裹，便于前端一键载入编辑器；
- 避免偷价与未来函数，始终进行序列长度安全检查。
【当前工作区上下文】:
${contextSnippet}`
    } else {
      return `你是一位资深宏观资产配置策略师与指数投资专家，为 QuantScope 平台提供专业市场洞察。
请以理性、严谨、客观且具备实战量化视角的语调回答用户关于 A 股盘面、宽基 ETF、大类资产配置、宏观经济周期与估值分析的问题。
回复要求排版精炼，逻辑清晰，重点突出，善于使用结构化列表与加粗突出要点。`
    }
  }

  // 6. 发起 AI 对话（流式 SSE）
  async function sendAiMessage(promptText: string, currentRoutePath: string = '/') {
    if (!promptText.trim() || isStreaming.value) return

    // 1. 追加用户消息
    const userMsgId = `user_${Date.now()}`
    messages.value.push({
      id: userMsgId,
      role: 'user',
      content: promptText.trim(),
      timestamp: Date.now(),
      pageContext: currentRoutePath,
    })

    // 2. 准备助手流式消息
    const assistantMsgId = `ai_${Date.now()}`
    const assistantMsg: AiChatMessage = {
      id: assistantMsgId,
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      pageContext: currentRoutePath,
      toolCalls: [],
      steps: [],
    }
    messages.value.push(assistantMsg)
    isStreaming.value = true

    try {
      const systemPrompt = buildSystemPrompt(currentRoutePath)

      // 提取多轮上下文 (保留最近 8 轮历史，剔除尚未生成的空消息)
      const historyMessages = messages.value
        .filter((m) => m.content && m.content.trim() && m.id !== assistantMsgId)
        .slice(-8)
        .map((m) => ({
          role: m.role,
          content: m.content,
        }))

      // 将当前用户问题压入末尾
      historyMessages.push({
        role: 'user',
        content: promptText.trim(),
      })

      const resp = await fetch('/api/v1/agent/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: historyMessages,
          model: aiModel.value,
          page_context: currentRoutePath,
          system_prompt: systemPrompt,
        }),
      })

      if (!resp.ok) {
        throw new Error(`智能体服务异常 (${resp.status}): ${await resp.text()}`)
      }

      const reader = resp.body?.getReader()
      if (!reader) throw new Error('无法创建流式读取器')

      const decoder = new TextDecoder('utf-8')
      let buffer = ''
      let currentEventType = 'message'

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed) {
            currentEventType = 'message'
            continue
          }

          if (trimmed.startsWith('event:')) {
            currentEventType = trimmed.slice(6).trim()
            continue
          }

          if (trimmed.startsWith('data:')) {
            const rawData = trimmed.slice(5).trim()
            if (rawData === '[DONE]' || currentEventType === 'done') {
              break
            }

            try {
              if (currentEventType === 'thought') {
                const th = JSON.parse(rawData)
                const stepNum = th.step || 1
                let stepObj = assistantMsg.steps?.find((s) => s.step === stepNum)
                if (!stepObj) {
                  stepObj = {
                    step: stepNum,
                    thought: th.thought,
                    toolCalls: [],
                    status: 'running',
                  }
                  assistantMsg.steps?.push(stepObj)
                } else {
                  stepObj.thought = th.thought
                }
              } else if (currentEventType === 'tool_call') {
                const call = JSON.parse(rawData)
                const stepNum = call.step || 1
                let stepObj = assistantMsg.steps?.find((s) => s.step === stepNum)
                if (!stepObj) {
                  stepObj = {
                    step: stepNum,
                    toolCalls: [],
                    status: 'running',
                  }
                  assistantMsg.steps?.push(stepObj)
                }

                const toolItem: AiToolCall = {
                  id: call.id,
                  name: call.name,
                  arguments: call.arguments,
                  status: 'calling',
                  step: stepNum,
                }

                if (!stepObj.toolCalls.find((t) => t.id === call.id)) {
                  stepObj.toolCalls.push(toolItem)
                }
                if (!assistantMsg.toolCalls?.find((t) => t.id === call.id)) {
                  assistantMsg.toolCalls?.push(toolItem)
                }
              } else if (currentEventType === 'tool_result') {
                const res = JSON.parse(rawData)
                const stepNum = res.step || 1
                const stepObj = assistantMsg.steps?.find((s) => s.step === stepNum)
                if (stepObj) {
                  const t = stepObj.toolCalls.find((x) => x.id === res.id)
                  if (t) {
                    t.status = 'done'
                    t.outputPreview = res.output_preview
                  }
                }
                const t2 = assistantMsg.toolCalls?.find((x) => x.id === res.id)
                if (t2) {
                  t2.status = 'done'
                  t2.outputPreview = res.output_preview
                }
              } else if (currentEventType === 'message') {
                // 收到消息正文时，将前面的步骤标记为已完成
                if (assistantMsg.steps) {
                  for (const s of assistantMsg.steps) {
                    s.status = 'done'
                  }
                }
                const parsed = JSON.parse(rawData)
                if (parsed.delta) {
                  assistantMsg.content += parsed.delta
                } else if (parsed.content) {
                  assistantMsg.content = parsed.content
                }
              }
            } catch {
              if (currentEventType === 'message') {
                assistantMsg.content += rawData
              }
            }
          }
        }
      }

      // 提取代码块供一键应用
      const codeBlock = extractPythonCode(assistantMsg.content)
      if (codeBlock) {
        assistantMsg.codeBlock = codeBlock
      }
    } catch (err: any) {
      assistantMsg.content += `\n\n> ⚠️ **调用异常**: ${err.message}`
    } finally {
      isStreaming.value = false
    }
  }

  // 清空对话历史
  function clearMessages() {
    messages.value = [
      {
        id: `welcome_${Date.now()}`,
        role: 'assistant',
        content: '✨ 已清空对话记录。我是 QuantScope 全局 AI 助手，请随时提出你的金融与量化需求！',
        timestamp: Date.now(),
      },
    ]
  }

  return {
    isOpen,
    position,
    triggerPosition,
    size,
    aiModel,
    isStreaming,
    messages,
    toggleOpen,
    open,
    close,
    updatePosition,
    updateSize,
    updateGeometry,
    getQuickPromptsForRoute,
    sendAiMessage,
    clearMessages,
    extractPythonCode,
  }
})
