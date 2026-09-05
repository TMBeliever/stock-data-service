import { marked, type Tokens } from 'marked'
import hljs from 'highlight.js'
import 'highlight.js/styles/atom-one-dark.css'

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}

// 自定义配置 Marked 渲染器
marked.use({
  breaks: true,
  gfm: true,
  renderer: {
    // 1. 代码块：语言高亮、顶栏元信息、复制与快捷应用到量化工作台
    code({ text, lang }: Tokens.Code) {
      const rawLanguage = (lang || '').trim().toLowerCase()
      // 去除可能携带的附加信息如 python {1-3}
      const language = rawLanguage.split(/\s+/)[0] || ''
      let highlightedCode = ''

      try {
        if (language && hljs.getLanguage(language)) {
          highlightedCode = hljs.highlight(text, { language, ignoreIllegals: true }).value
        } else {
          highlightedCode = hljs.highlightAuto(text).value
        }
      } catch {
        highlightedCode = escapeHtml(text)
      }

      const displayLang = (language || 'TEXT').toUpperCase()
      const isPythonOrStrategy =
        language === 'python' ||
        language === 'py' ||
        text.includes('Strategy') ||
        text.includes('def on_bar') ||
        text.includes('class ')

      const encodedCode = encodeURIComponent(text)

      return `
<div class="code-block-container my-3 rounded-xl overflow-hidden border border-white/[0.12] bg-[#0f1016] shadow-md group">
  <div class="code-block-header flex items-center justify-between px-3.5 py-1.5 bg-white/[0.04] border-b border-white/[0.08] text-[11px] font-mono select-none">
    <div class="flex items-center space-x-1.5 text-zinc-300">
      <span class="text-purple-400 font-bold">&lt;/&gt;</span>
      <span class="font-semibold tracking-wide text-zinc-200">${displayLang}</span>
    </div>
    <div class="flex items-center space-x-2 text-zinc-400">
      ${
        isPythonOrStrategy
          ? `<button class="apply-editor-btn hover:text-amber-400 transition-colors cursor-pointer flex items-center space-x-1 px-1.5 py-0.5 rounded hover:bg-white/[0.06]" data-code="${encodedCode}" title="载入代码到量化工作台编辑器">
              <span>⚡</span>
              <span>载入工作台</span>
            </button>`
          : ''
      }
      <button class="copy-code-btn hover:text-white transition-colors cursor-pointer flex items-center space-x-1 px-1.5 py-0.5 rounded hover:bg-white/[0.06]" data-code="${encodedCode}" title="复制代码">
        <span>📋</span>
        <span>复制</span>
      </button>
    </div>
  </div>
  <pre class="hljs p-3.5 text-[11.5px] font-mono leading-relaxed overflow-x-auto m-0 bg-[#0d0e14] text-zinc-200"><code>${highlightedCode}</code></pre>
</div>`
    },

    // 2. 行内代码
    codespan({ text }: Tokens.Codespan) {
      return `<code class="px-1.5 py-0.5 rounded bg-white/[0.08] text-amber-300 font-mono text-[11px] border border-white/[0.06] mx-0.5">${text}</code>`
    },
  },
})

/**
 * 格式化渲染 Markdown 内容
 */
export function renderMarkdown(content: string): string {
  if (!content) return ''
  try {
    return marked.parse(content) as string
  } catch (err) {
    console.warn('Failed to parse markdown:', err)
    return escapeHtml(content)
  }
}

/**
 * 为任意独立代码片段生成高亮 HTML (例如 Codex 卡片中的代码)
 */
export function highlightCodeSnippet(code: string, language?: string): string {
  if (!code) return ''
  const lang = (language || '').trim().toLowerCase()
  try {
    if (lang && hljs.getLanguage(lang)) {
      return hljs.highlight(code, { language: lang, ignoreIllegals: true }).value
    }
    return hljs.highlightAuto(code).value
  } catch {
    return escapeHtml(code)
  }
}
