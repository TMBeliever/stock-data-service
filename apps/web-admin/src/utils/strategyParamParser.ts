/**
 * Python 策略代码参数解析与双向精准替换引擎 (Strategy Parameter Parser & Two-Way Code Binder)
 * 
 * 核心能力：
 * 1. 静态扫描 Python 策略类的 __init__ 构造函数，提取参数名、默认值、类型与注释元数据；
 * 2. 支持 `@param label="中文标签" min=2 max=30 step=1 unit="日" group="buy"` 高级扩展注解；
 * 3. 具备金融量化命名语义智能推断（如 pct 自动推导为百分比滑块、window 自动推导为周期）；
 * 4. updateCodeParam：在保持 Python 原本代码缩进、注释与换行完全不变的前提下，精准替换默认实参！
 */

export interface StrategyParam {
  key: string
  name: string
  label: string
  type: 'int' | 'float' | 'percent' | 'bool' | 'select'
  value: any
  defaultValue: any
  min: number
  max: number
  step: number
  unit: string
  group: 'buy' | 'sell' | 'capital' | 'risk' | 'general'
  description?: string
  options?: { label: string; value: any }[]
}

export interface StrategyParsedInfo {
  className: string
  docstring: string
  plainSummary: string
  summary: string
  params: StrategyParam[]
}

export type ParsedStrategyParam = StrategyParam
export type StrategyMetaInfo = StrategyParsedInfo

/**
 * 语义化默认标签字典 (针对量化常用参数的中文映射)
 */
const SEMANTIC_PARAM_DICTIONARY: Record<string, { label: string; group: StrategyParam['group']; unit?: string }> = {
  fast: { label: '短期均线周期 (Fast)', group: 'buy', unit: '日' },
  fast_period: { label: '短期均线周期 (Fast)', group: 'buy', unit: '日' },
  slow: { label: '长期均线周期 (Slow)', group: 'sell', unit: '日' },
  slow_period: { label: '长期均线周期 (Slow)', group: 'sell', unit: '日' },
  window: { label: '历史回看评估窗口', group: 'general', unit: '天' },
  period: { label: '指标计算周期', group: 'general', unit: '天' },
  buy_percentile: { label: '低估买入分位阈值', group: 'buy', unit: '%' },
  buy_pct: { label: '低估买入分位阈值', group: 'buy', unit: '%' },
  sell_percentile: { label: '高估止盈分位阈值', group: 'sell', unit: '%' },
  sell_pct: { label: '高估止盈分位阈值', group: 'sell', unit: '%' },
  multiplier: { label: '低估加倍加仓杠杆', group: 'capital', unit: '倍' },
  reduce_ratio: { label: '高估分批减仓比例', group: 'sell', unit: '%' },
  base_amount: { label: '单期定投基准金额', group: 'capital', unit: '元' },
  target_pct: { label: '开仓目标仓位比例', group: 'capital', unit: '%' },
  target_percent: { label: '开仓目标仓位比例', group: 'capital', unit: '%' },
  step_pct: { label: '网格间距波动比例', group: 'general', unit: '%' },
  base_shares: { label: '网格单笔基准股数', group: 'capital', unit: '股' },
  stop_loss: { label: '移动动态止损线', group: 'sell', unit: '%' },
  stop_loss_pct: { label: '移动动态止损线', group: 'sell', unit: '%' },
  take_profit: { label: '硬性止盈目标线', group: 'sell', unit: '%' },
  rsi_period: { label: 'RSI 计算周期', group: 'general', unit: '日' },
  rsi_oversold: { label: 'RSI 超卖抄底阈值', group: 'buy', unit: '' },
  rsi_overbought: { label: 'RSI 超买止盈阈值', group: 'sell', unit: '' },
}

/**
 * 解析 Python 策略源码
 */
export function parseStrategyCode(code: string): StrategyParsedInfo {
  if (!code || !code.trim()) {
    return {
      className: '',
      docstring: '',
      plainSummary: '暂未检测到有效策略类',
      summary: '暂未检测到有效策略类',
      params: [],
    }
  }

  // 1. 提取类名
  const classMatch = code.match(/class\s+([A-Za-z0-9_]+)\s*(?:\([^)]*\))?:/)
  const className = classMatch ? classMatch[1] : 'CustomStrategy'

  // 2. 提取 Docstring 文档注释
  let docstring = ''
  const docMatch = code.match(/class[\s\S]*?:\s*"""([\s\S]*?)"""/)
  if (docMatch && docMatch[1]) {
    docstring = docMatch[1].trim()
  }

  // 3. 生成白话总结
  let plainSummary = docstring.split('\n')[0]?.trim() || ''
  if (!plainSummary) {
    plainSummary = `基于 ${className} 架构的自动化量化交易策略`
  }

  // 4. 定位 def __init__(self, ...):
  const initMatch = code.match(/def\s+__init__\s*\(\s*self\s*,?([\s\S]*?)\)\s*:/)
  const params: StrategyParam[] = []

  if (initMatch && initMatch[1]) {
    const rawParamsBlock = initMatch[1]
    
    // 按行拆分，以准确匹配行尾注释
    const lines = rawParamsBlock.split('\n')
    let accumulatedParam = ''

    lines.forEach((line) => {
      const trimmed = line.trim()
      if (!trimmed || trimmed.startsWith('#')) return

      accumulatedParam += ' ' + trimmed
      if (trimmed.endsWith(',') || !trimmed.includes('(') || trimmed.endsWith(')')) {
        parseSingleParamDeclaration(accumulatedParam, params)
        accumulatedParam = ''
      }
    })

    if (accumulatedParam.trim()) {
      parseSingleParamDeclaration(accumulatedParam, params)
    }
  }

  return {
    className,
    docstring,
    plainSummary,
    summary: plainSummary,
    params,
  }
}

export const parseStrategyParams = parseStrategyCode

/**
 * 解析单条形参声明（支持类型、默认值与行尾 @param 或普通注释）
 */
function parseSingleParamDeclaration(raw: string, paramsList: StrategyParam[]) {
  const clean = raw.trim().replace(/,$/, '')
  if (!clean || clean.startsWith('*')) return

  // 分离代码部分与行尾注释部分
  let codePart = clean
  let commentPart = ''
  const hashIdx = clean.indexOf('#')
  if (hashIdx !== -1) {
    codePart = clean.slice(0, hashIdx).trim()
    commentPart = clean.slice(hashIdx + 1).trim()
  }

  // 拆分参数名与默认值：name[: type] = default_val
  const eqIdx = codePart.indexOf('=')
  if (eqIdx === -1) return // 无默认值的跳过

  const left = codePart.slice(0, eqIdx).trim()
  const right = codePart.slice(eqIdx + 1).trim()

  // 解析名字与类型
  let key = left
  let typeAnnotation = ''
  if (left.includes(':')) {
    const parts = left.split(':')
    key = parts[0].trim()
    typeAnnotation = parts[1].trim()
  }

  if (key === 'self' || key === 'args' || key === 'kwargs') return

  // 解析默认值
  let defaultVal: any = right
  let inferredType: StrategyParam['type'] = 'float'

  if (right === 'True' || right === 'False') {
    defaultVal = right === 'True'
    inferredType = 'bool'
  } else if (/^-?\d+$/.test(right)) {
    defaultVal = parseInt(right, 10)
    inferredType = 'int'
  } else if (/^-?\d+\.\d+$/.test(right)) {
    defaultVal = parseFloat(right)
    inferredType = defaultVal > 0 && defaultVal <= 1.0 ? 'percent' : 'float'
  } else if (right.startsWith('"') || right.startsWith("'")) {
    defaultVal = right.slice(1, -1)
    inferredType = 'select'
  }

  // 语义推断
  const lowerKey = key.toLowerCase()
  const semantic = SEMANTIC_PARAM_DICTIONARY[lowerKey] || inferSemanticByKey(lowerKey, defaultVal)

  let label = semantic.label
  let group = semantic.group
  let unit = semantic.unit || ''
  let min = 0
  let max = 100
  let step = 1

  // 针对数值范围的默认推断
  if (inferredType === 'int') {
    if (defaultVal <= 30) {
      min = 2
      max = 60
      step = 1
    } else {
      min = 10
      max = 500
      step = 5
    }
  } else if (inferredType === 'percent') {
    min = 0.01
    max = 1.0
    step = 0.01
    unit = '%'
  } else if (inferredType === 'float') {
    if (defaultVal <= 5.0) {
      min = 0.1
      max = 10.0
      step = 0.1
    } else {
      min = 100
      max = 100000
      step = 500
      unit = '元'
    }
  }

  // 5. 高级 @param 注解覆盖解析 (例如: # @param label="快线周期" min=2 max=30 step=1 unit="日")
  if (commentPart) {
    if (commentPart.includes('@param')) {
      const labelMatch = commentPart.match(/label=["']([^"']+)["']/)
      if (labelMatch) label = labelMatch[1]

      const minMatch = commentPart.match(/min=([0-9.]+)/)
      if (minMatch) min = parseFloat(minMatch[1])

      const maxMatch = commentPart.match(/max=([0-9.]+)/)
      if (maxMatch) max = parseFloat(maxMatch[1])

      const stepMatch = commentPart.match(/step=([0-9.]+)/)
      if (stepMatch) step = parseFloat(stepMatch[1])

      const unitMatch = commentPart.match(/unit=["']([^"']*)["']/)
      if (unitMatch) unit = unitMatch[1]

      const groupMatch = commentPart.match(/group=["']([^"']+)["']/)
      if (groupMatch) group = groupMatch[1] as any
    } else if (!SEMANTIC_PARAM_DICTIONARY[lowerKey]) {
      // 若无 @param 但有普通注释，将普通注释前 10 个字作为标签
      const simpleNote = commentPart.replace(/^[：:\s-]+/, '').trim()
      if (simpleNote && simpleNote.length <= 15) {
        label = simpleNote
      }
    }
  }

  paramsList.push({
    key,
    name: key,
    label,
    type: inferredType,
    value: defaultVal,
    defaultValue: defaultVal,
    min,
    max,
    step,
    unit,
    group,
  })
}

/**
 * 智能根据变量命名词根推断 Label 与 Group
 */
function inferSemanticByKey(lowerKey: string, val: any): { label: string; group: StrategyParam['group']; unit?: string } {
  let group: StrategyParam['group'] = 'general'
  let unit = ''

  if (lowerKey.includes('buy') || lowerKey.includes('fast') || lowerKey.includes('entry') || lowerKey.includes('under')) {
    group = 'buy'
  } else if (lowerKey.includes('sell') || lowerKey.includes('slow') || lowerKey.includes('stop') || lowerKey.includes('exit') || lowerKey.includes('over')) {
    group = 'sell'
  } else if (lowerKey.includes('amount') || lowerKey.includes('cash') || lowerKey.includes('target') || lowerKey.includes('share') || lowerKey.includes('mult')) {
    group = 'capital'
  }

  // 美化驼峰/下划线命名
  let label = lowerKey
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())

  if (lowerKey.includes('period') || lowerKey.includes('window') || lowerKey.includes('days')) {
    unit = '日'
  } else if (lowerKey.includes('pct') || lowerKey.includes('ratio') || lowerKey.includes('rate') || (typeof val === 'number' && val > 0 && val <= 1.0)) {
    unit = '%'
  } else if (lowerKey.includes('amount') || lowerKey.includes('cash')) {
    unit = '元'
  }

  return { label, group, unit }
}

/**
 * 精准替换 Python 源码中 __init__ 的指定参数默认值 (保持缩进与注释完全不变)
 * 
 * @param code 当前完整 Python 策略源码
 * @param paramKey 要修改的参数名 (如 fast_period)
 * @param newValue 新数值 (如 8)
 * @returns 替换后的完整源码
 */
export function updateCodeParam(code: string, paramKey: string, newValue: any): string {
  if (!code || !paramKey) return code

  // 格式化新值
  let formattedVal = String(newValue)
  if (typeof newValue === 'boolean') {
    formattedVal = newValue ? 'True' : 'False'
  } else if (typeof newValue === 'number') {
    // 整数或浮点数格式化
    formattedVal = Number.isInteger(newValue) ? String(newValue) : String(Number(newValue.toFixed(4)))
  } else if (typeof newValue === 'string') {
    formattedVal = `"${newValue}"`
  }

  // 正则匹配 __init__ 中的 paramKey\s*(:[^=]+)?\s*=\s*([^,\n#]+)
  // 仅在 __init__ 参数区域内进行替换
  const initRegex = /(def\s+__init__\s*\([\s\S]*?\)\s*:)/
  const match = code.match(initRegex)
  if (!match) return code

  const initBlock = match[1]
  
  // 构造针对特定参数的正则：key 紧跟可选类型注解，再跟 =，再跟旧值
  const paramRegex = new RegExp(`(\\b${paramKey}\\s*(?::\\s*[^=,]+)?\\s*=\\s*)([^,\\s\\n#)]+)`, 'g')

  if (!paramRegex.test(initBlock)) {
    return code
  }

  paramRegex.lastIndex = 0
  const updatedInitBlock = initBlock.replace(paramRegex, (_full, prefix) => {
    return `${prefix}${formattedVal}`
  })

  return code.replace(initBlock, updatedInitBlock)
}

/**
 * 一次性将一组新参数全部应用到 Python 源码中
 */
export function applyAllParamsToCode(code: string, paramValues: Record<string, any>): string {
  let updated = code
  for (const [k, v] of Object.entries(paramValues)) {
    updated = updateCodeParam(updated, k, v)
  }
  return updated
}
