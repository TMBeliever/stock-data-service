/**
 * 生产环境通用剪贴板与工具链导出工具 (Universal Clipboard & Toolchain Export Utility)
 * 解决在 HTTP 非安全上下文 (如直接通过 IP 访问 http://ip:port) 下 navigator.clipboard 为 undefined 导致的复制失效问题
 */

/**
 * 兼容全平台与 HTTP/HTTPS 环境的通用文本复制函数
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  if (text === undefined || text === null) return false

  const str = String(text)

  // 1. 优先尝试现代异步 Clipboard API (必须处于 Secure Context 即 https 或 localhost)
  if (
    typeof window !== 'undefined' &&
    window.isSecureContext &&
    navigator?.clipboard &&
    typeof navigator.clipboard.writeText === 'function'
  ) {
    try {
      await navigator.clipboard.writeText(str)
      return true
    } catch (err) {
      console.warn('navigator.clipboard.writeText failed, attempting execCommand fallback:', err)
    }
  }

  // 2. 降级方案：创建不可见 textarea 元素并通过 document.execCommand('copy') 完成复制 (兼容 HTTP IP 访问)
  try {
    const textArea = document.createElement('textarea')
    textArea.value = str
    textArea.style.position = 'fixed'
    textArea.style.top = '-99999px'
    textArea.style.left = '-99999px'
    textArea.style.width = '2em'
    textArea.style.height = '2em'
    textArea.style.padding = '0'
    textArea.style.border = 'none'
    textArea.style.outline = 'none'
    textArea.style.boxShadow = 'none'
    textArea.style.background = 'transparent'
    textArea.setAttribute('readonly', '')
    document.body.appendChild(textArea)

    textArea.focus({ preventScroll: true })
    textArea.select()
    textArea.setSelectionRange(0, str.length)

    const successful = document.execCommand('copy')
    document.body.removeChild(textArea)
    if (successful) {
      return true
    }
  } catch (err) {
    console.warn('document.execCommand copy failed, attempting selection fallback:', err)
  }

  // 3. 兜底方案：通过 Range/Selection 选区复制
  try {
    const span = document.createElement('span')
    span.textContent = str
    span.style.position = 'fixed'
    span.style.top = '-99999px'
    span.style.left = '-99999px'
    span.style.whiteSpace = 'pre'
    document.body.appendChild(span)

    const selection = window.getSelection()
    const range = document.createRange()
    range.selectNodeContents(span)
    selection?.removeAllRanges()
    selection?.addRange(range)

    const successful = document.execCommand('copy')
    selection?.removeAllRanges()
    document.body.removeChild(span)
    return successful
  } catch (err) {
    console.error('All clipboard copy attempts failed:', err)
    return false
  }
}

/**
 * 将工具名称格式化为可读中文名称
 */
export function getFriendlyToolName(name: string): string {
  const map: Record<string, string> = {
    admin_inspect_system_and_services: '全景健康体检',
    admin_read_source_code: '阅读源码文件',
    admin_modify_source_code: '编译修改源码',
    admin_run_tests: '自动化测试运行',
    admin_manage_service: '微服务生命周期管理',
    admin_docker_manage: 'Docker 容器与集群运维',
    admin_execute_shell: '宿主机 Shell 终端执行',
    run_command: 'Shell 命令行执行',
    get_realtime_quote: '行情数据查询 (实时快照)',
    get_stock_kline: '历史行情 K 线数据',
    get_stock_valuation: '基本面与个股估值',
    get_market_overview: '全市场大盘与板块情绪',
    validate_strategy_code: '量化策略语法规范校验',
    run_backtest_fast: '沙箱极速量化回测',
  }
  return map[name] || name
}

/**
 * 格式化单个工具调用项为清晰的 Markdown 格式文本
 */
export function formatSingleToolCall(tc: any, index?: number): string {
  if (!tc) return ''

  const prefix = index !== undefined ? `### [步骤 ${index}] ` : '### '
  const friendlyName = getFriendlyToolName(tc.name || 'unknown')
  const statusMap: Record<string, string> = {
    calling: '⏳ 执行中',
    done: '✓ 执行完成',
    failed: '✕ 执行异常',
    waiting_approval: '🛡️ 等待授权',
    rejected: '✕ 用户拒绝',
  }
  const statusText = statusMap[tc.status] || tc.status || '已执行'

  let text = `${prefix}${friendlyName} (\`${tc.name}\`)\n`
  text += `- 状态: ${statusText}\n`

  // 参数部分
  if (tc.arguments && Object.keys(tc.arguments).length > 0) {
    if (tc.arguments.command) {
      text += `- 执行命令: \`${tc.arguments.command}\`\n`
    } else if (tc.arguments.action) {
      text += `- 执行动作: \`${tc.arguments.action}\` ${tc.arguments.args ? `(参数: ${tc.arguments.args})` : ''}\n`
    } else {
      try {
        const argsJson = JSON.stringify(tc.arguments, null, 2)
        text += `- 调用参数:\n\`\`\`json\n${argsJson}\n\`\`\`\n`
      } catch {
        text += `- 调用参数: ${String(tc.arguments)}\n`
      }
    }
  }

  // 输出部分
  const output = tc.liveOutput || tc.outputPreview
  if (output && output.trim()) {
    text += `- 执行输出 / 返回结果:\n\`\`\`\n${output.trim()}\n\`\`\`\n`
  }

  return text
}

/**
 * 将整条消息的工具链转换为美观规范的 Markdown
 */
export function formatToolchainMarkdown(toolCalls: any[]): string {
  if (!toolCalls || toolCalls.length === 0) return ''

  const lines: string[] = [
    `## 🛠️ 工具链执行流程记录 (共 ${toolCalls.length} 步)`,
    ''
  ]

  toolCalls.forEach((tc, idx) => {
    lines.push(formatSingleToolCall(tc, idx + 1))
  })

  return lines.join('\n')
}

/**
 * 完整导出整条 Assistant 消息（包含推演思考、工具链、正文与代码卡片）
 */
export function formatFullMessageForCopy(msg: any): string {
  if (!msg) return ''

  const parts: string[] = []

  // 1. 思考过程 (如果存在)
  if (msg.thought && msg.thought.trim()) {
    parts.push(`> 💭 **推演思考**: ${msg.thought.trim()}\n`)
  }

  // 2. 工具链执行记录 (如果存在)
  if (msg.toolCalls && msg.toolCalls.length > 0) {
    parts.push(formatToolchainMarkdown(msg.toolCalls))
    parts.push('')
  }

  // 3. 回答正文
  if (msg.content && msg.content.trim()) {
    if (msg.toolCalls && msg.toolCalls.length > 0) {
      parts.push('## 💡 投研诊断与推演结论\n')
    }
    parts.push(msg.content.trim())
  }

  // 4. 独立代码卡片 (如果存在)
  if (msg.cards && msg.cards.length > 0) {
    parts.push('\n## 📁 关联代码与策略文件\n')
    for (const card of msg.cards) {
      parts.push(`### 📄 ${card.title || '代码片段'} (${card.language || 'python'})`)
      parts.push(`\`\`\`${card.language || 'python'}\n${card.content}\n\`\`\`\n`)
    }
  }

  // 若均为空则返回空字符串
  return parts.join('\n').trim()
}
