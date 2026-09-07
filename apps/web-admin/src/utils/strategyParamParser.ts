/**
 * Python 策略代码参数解析与双向精准替换引擎 (Strategy Parameter Parser & Two-Way Code Binder)
 * 
 * 核心能力：
 * 1. 静态扫描 Python 策略类的 __init__ 构造函数，提取参数名、默认值、类型与注释元数据；
 * 2. 支持 `@param label="中文标签" min=2 max=30 step=1 unit="日" group="buy"` 高级扩展注解；
 * 3. 具备金融量化命名语义智能推断（如 bottom 识别为大底、dip 识别为暴跌抄底、rebound 识别为反弹）；
 * 4. 自动智能过滤 AI 历史修补日志（如“移除不存在的 self.bars...”），提取真正的量化交易策略白话业务描述；
 * 5. updateCodeParam：在保持 Python 原本代码缩进、注释与换行完全不变的前提下，精准替换默认实参！
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
  desc?: string
  description?: string
  options?: { label: string; value: any }[]
}

export interface StrategyParsedInfo {
  className: string
  docstring: string
  plainSummary: string
  summary: string
  rules: string[]
  params: StrategyParam[]
}

export type ParsedStrategyParam = StrategyParam
export type StrategyMetaInfo = StrategyParsedInfo

/**
 * 语义化默认标签字典 (针对量化常用参数的中文人话映射与小白通俗解释)
 */
const SEMANTIC_PARAM_DICTIONARY: Record<string, { label: string; desc: string; group: StrategyParam['group']; unit?: string; min?: number; max?: number; step?: number }> = {
  // 均线与基础周期
  fast: { label: '短期快均线周期', desc: '敏感跟踪短期价格变动，数值越小越灵敏，数值越大越平滑稳健', group: 'buy', unit: '天', min: 2, max: 30, step: 1 },
  fast_period: { label: '短期快均线周期', desc: '敏感跟踪短期价格变动，数值越小越灵敏，数值越大越平滑稳健', group: 'buy', unit: '天', min: 2, max: 30, step: 1 },
  slow: { label: '长期慢均线周期', desc: '平滑过滤短期杂波噪音，代表中长期趋势的基准方向', group: 'sell', unit: '天', min: 10, max: 120, step: 5 },
  slow_period: { label: '长期慢均线周期', desc: '平滑过滤短期杂波噪音，代表中长期趋势的基准方向', group: 'sell', unit: '天', min: 10, max: 120, step: 5 },
  window: { label: '历史数据回看天数', desc: '向前回溯评估指标（如高低点、分位数、均值）的统计窗口长度', group: 'general', unit: '天', min: 30, max: 500, step: 10 },
  period: { label: '指标计算周期', desc: '计算当前技术指标所参考的连续交易天数', group: 'general', unit: '天', min: 5, max: 250, step: 5 },
  lookback: { label: '历史数据回看天数', desc: '向前回溯评估指标统计窗口长度（天）', group: 'general', unit: '天', min: 20, max: 500, step: 10 },

  // 底仓与基础资金 (彻底杜绝 base 比例阈值)
  base: { label: '初始底仓配置比例', desc: '策略初次启动时建立的打底仓位比例，保障持有基础筹码，避免空仓踏空', group: 'capital', unit: '%', min: 0.10, max: 0.80, step: 0.05 },
  base_pct: { label: '初始底仓配置比例', desc: '策略初次启动时建立的打底仓位比例，保障持有基础筹码，避免空仓踏空', group: 'capital', unit: '%', min: 0.10, max: 0.80, step: 0.05 },
  base_ratio: { label: '初始底仓配置比例', desc: '策略初次启动时建立的打底仓位比例，保障持有基础筹码，避免空仓踏空', group: 'capital', unit: '%', min: 0.10, max: 0.80, step: 0.05 },
  initial_ratio: { label: '初始底仓配置比例', desc: '策略初次启动时建立的打底仓位比例，保障持有基础筹码，避免空仓踏空', group: 'capital', unit: '%', min: 0.10, max: 0.80, step: 0.05 },
  base_amount: { label: '每期基准定投金额', desc: '每个定投周期固定的基础买入金额（元），当估值极低时会自动加倍扣款', group: 'capital', unit: '元', min: 500, max: 10000, step: 500 },
  base_shares: { label: '网格单格交易股数', desc: '每当价格涨跌触及网格轨道时，单笔固定高抛低吸买卖的股票或ETF份数', group: 'capital', unit: '股', min: 100, max: 5000, step: 100 },

  // 估值与抄底
  bottom_window: { label: '历史大底回溯周期', desc: '向前寻找极端历史大底的时间跨度（天），通常 250 天对应近一年的年内大底', group: 'buy', unit: '天', min: 60, max: 500, step: 10 },
  buy_percentile: { label: '极度低估买入分位', desc: '历史价格分位数低于该比例时认定处于极端黄金坑，触发低吸建仓', group: 'buy', unit: '%', min: 0.05, max: 0.50, step: 0.05 },
  buy_undervalue_pct: { label: '极度低估买入分位', desc: '历史价格分位数低于该比例时认定处于极端黄金坑，触发低吸建仓', group: 'buy', unit: '%', min: 0.05, max: 0.40, step: 0.05 },
  buy_pct: { label: '极度低估买入分位', desc: '历史价格分位数低于该比例时认定处于极端黄金坑，触发低吸建仓', group: 'buy', unit: '%', min: 0.05, max: 0.50, step: 0.05 },
  dip_threshold: { label: '极端暴跌抄底阈值', desc: '从阶段最高价回撤跌幅达该比例时果断重仓抄底（如 15% 对应自高位急跌 15%）', group: 'buy', unit: '%', min: 0.05, max: 0.40, step: 0.01 },
  dip_pct: { label: '极端暴跌抄底阈值', desc: '从阶段最高价回撤跌幅达该比例时果断重仓抄底（如 15% 对应自高位急跌 15%）', group: 'buy', unit: '%', min: 0.05, max: 0.40, step: 0.01 },
  rebound_pct: { label: '触底反弹确认幅度', desc: '触及大底后从最低点回升达该幅度时确认反转成立，触发右侧稳健买入', group: 'buy', unit: '%', min: 0.01, max: 0.15, step: 0.005 },
  rebound_bars: { label: '触底反弹观察天数', desc: '触及大底后观察企稳反弹形态的交易天数窗口', group: 'buy', unit: '天', min: 1, max: 20, step: 1 },
  multiplier: { label: '低估加倍定投系数', desc: '当处于极度低估安全区时，将单期买入金额放大的倍数（如 2.0 代表买入双倍金额）', group: 'buy', unit: '倍', min: 1.0, max: 4.0, step: 0.5 },
  undervalue_multiplier: { label: '低估加倍定投系数', desc: '当处于极度低估安全区时，将单期买入金额放大的倍数（如 2.0 代表买入双倍金额）', group: 'buy', unit: '倍', min: 1.0, max: 4.0, step: 0.5 },

  // 止盈与风控
  sell_percentile: { label: '严重高估止盈分位', desc: '历史价格分位数高于该比例时认定处于亢奋泡沫期，主动减仓兑现收益', group: 'sell', unit: '%', min: 0.50, max: 0.95, step: 0.05 },
  sell_overvalue_pct: { label: '严重高估止盈分位', desc: '历史价格分位数高于该比例时认定处于亢奋泡沫期，主动减仓兑现收益', group: 'sell', unit: '%', min: 0.60, max: 0.95, step: 0.05 },
  sell_pct: { label: '严重高估止盈分位', desc: '历史价格分位数高于该比例时认定处于亢奋泡沫期，主动减仓兑现收益', group: 'sell', unit: '%', min: 0.50, max: 0.95, step: 0.05 },
  take_profit_ratio: { label: '高估止盈减仓比例', desc: '每次触发止盈信号时，从已有持仓中卖出变现的股份百分比（如减持 20%）', group: 'sell', unit: '%', min: 0.10, max: 0.50, step: 0.05 },
  reduce_ratio: { label: '高估止盈减仓比例', desc: '每次触发止盈信号时，从已有持仓中卖出变现的股份百分比（如减持 20%）', group: 'sell', unit: '%', min: 0.10, max: 0.50, step: 0.05 },
  take_profit_pct: { label: '硬性止盈目标线', desc: '当单笔持仓累计盈利达到该百分比时坚决落袋为安，避免利润坐过山车', group: 'sell', unit: '%', min: 0.05, max: 0.80, step: 0.05 },
  take_profit: { label: '硬性止盈目标线', desc: '当单笔持仓累计盈利达到该百分比时坚决落袋为安，避免利润坐过山车', group: 'sell', unit: '%', min: 0.05, max: 0.80, step: 0.05 },
  stop_loss_pct: { label: '风控动态止损线', desc: '当单笔持仓浮亏触及该比例时坚决止损斩仓，切断本金毁灭性亏损', group: 'sell', unit: '%', min: 0.01, max: 0.20, step: 0.01 },
  stop_loss: { label: '风控动态止损线', desc: '当单笔持仓浮亏触及该比例时坚决止损斩仓，切断本金毁灭性亏损', group: 'sell', unit: '%', min: 0.01, max: 0.20, step: 0.01 },
  trailing_stop_pct: { label: '移动回撤保护线', desc: '从持仓最高盈利点回撤达该比例时触发止盈出场，保护已有浮盈', group: 'sell', unit: '%', min: 0.01, max: 0.15, step: 0.005 },
  ma_period: { label: '价格回归均线周期', desc: '超跌反弹后价格向上重新站上该日均线时视为修复到位，分批减仓', group: 'sell', unit: '天', min: 10, max: 120, step: 5 },

  // 仓位与网格
  target_percent: { label: '开仓目标仓位比例', desc: '买入建仓时，该标的在总资产中所占的目标资金仓位比例（如 80%）', group: 'capital', unit: '%', min: 0.20, max: 1.0, step: 0.05 },
  target_pct: { label: '开仓目标仓位比例', desc: '买入建仓时，该标的在总资产中所占的目标资金仓位比例（如 80%）', group: 'capital', unit: '%', min: 0.10, max: 1.0, step: 0.05 },
  pos_ratio: { label: '开仓目标仓位比例', desc: '买入建仓时，该标的在总资产中所占的目标资金仓位比例（如 80%）', group: 'capital', unit: '%', min: 0.10, max: 1.0, step: 0.05 },
  step_pct: { label: '网格间距波动比例', desc: '相邻两层网格之间的价格涨跌百分比差，达到该波动便自动低吸或高抛', group: 'general', unit: '%', min: 0.01, max: 0.08, step: 0.005 },

  // 逻辑开关 (杜绝形如 Enable Rsi Filter 的英文机械拼接)
  enable_rsi_filter: { label: 'RSI 超买超卖过滤开关', desc: '开启后在市场处于极端过热（RSI>70）时暂停追高，防范假突破套牢', group: 'buy' },
  enable_trend_filter: { label: '多头大趋势保护开关', desc: '开启后仅在价格处于长期均线之上的多头顺势格局中才允许开仓交易', group: 'buy' },
  enable_stop_loss: { label: '风控动态止损开关', desc: '开启后将对所有持仓执行硬性最大亏损保护，拒绝被动深套', group: 'sell' },
  enable_take_profit: { label: '目标阶梯止盈开关', desc: '开启后在达到预设收益目标线时主动分批出场锁定胜利果实', group: 'sell' },
  enable_trailing_stop: { label: '移动追踪止盈开关', desc: '开启后止盈线将跟随最高价动态上移，回撤指定幅度自动锁定最高收益', group: 'sell' },

  // 资产配置大类
  stock_weight: { label: '股票权益配置权重', desc: '资产配置组合中投资于股票或股票型ETF的比例，主要负责捕捉经济增长收益', group: 'capital', unit: '%', min: 0.05, max: 0.80, step: 0.05 },
  long_bond_weight: { label: '长期国债配置权重', desc: '配置于超长久期国债的比例，在市场萧条与利率下行期提供丰厚避险收益', group: 'capital', unit: '%', min: 0.05, max: 0.80, step: 0.05 },
  inter_bond_weight: { label: '中期纯债配置权重', desc: '配置于中期高信用纯债的比例，有效平滑组合整体回撤并提供日常充沛流动性', group: 'capital', unit: '%', min: 0.05, max: 0.80, step: 0.05 },
  gold_weight: { label: '黄金大类配置权重', desc: '配置于黄金ETF的比例，对抗信用货币超发贬值与极端地缘黑天鹅冲击', group: 'capital', unit: '%', min: 0.01, max: 0.30, step: 0.01 },
  commodity_weight: { label: '大宗商品配置权重', desc: '配置于有色金属、能源大宗商品的比例，用于对冲恶性通货膨胀风险', group: 'capital', unit: '%', min: 0.01, max: 0.30, step: 0.01 },
  rebalance_band: { label: '再平衡偏离容忍阈值', desc: '当某类资产实际权重偏离目标达该比例时，自动触发调仓卖高买低回归中枢', group: 'general', unit: '%', min: 0.01, max: 0.10, step: 0.005 },
  rebalance_interval: { label: '定期再平衡评估天数', desc: '每隔多少个交易日对投资组合进行一次偏离度检查与动态再平衡操作', group: 'general', unit: '天', min: 5, max: 60, step: 5 },
  single_symbol_target: { label: '单只标的持仓上限', desc: '任何单一投资标的所能占用的最大仓位比例，防范单一黑天鹅踩雷', group: 'capital', unit: '%', min: 0.10, max: 0.80, step: 0.05 },
}

/**
 * 顶级安全逗号拆分函数（不拆分括号内或引号内的逗号）
 */
function splitByTopLevelComma(str: string): string[] {
  const result: string[] = []
  let current = ''
  let inParen = 0
  let inQuote: string | null = null

  for (let i = 0; i < str.length; i++) {
    const char = str[i]
    if (inQuote) {
      if (char === inQuote) inQuote = null
      current += char
    } else if (char === '"' || char === "'") {
      inQuote = char
      current += char
    } else if (char === '(' || char === '[' || char === '{') {
      inParen++
      current += char
    } else if (char === ')' || char === ']' || char === '}') {
      inParen--
      current += char
    } else if (char === ',' && inParen === 0) {
      result.push(current.trim())
      current = ''
    } else {
      current += char
    }
  }
  result.push(current.trim())
  return result
}

/**
 * 智能根据变量命名词根推断小白人话中文 Label、通俗解释 Desc、Group、Unit 与合理区间
 */
function inferQuantSemanticByKey(
  rawKey: string,
  val: any
): { label: string; desc: string; group: StrategyParam['group']; unit: string; min: number; max: number; step: number } {
  const lower = rawKey.toLowerCase().replace(/[\s-]+/g, '_').trim()

  // 1. 优先完全匹配超级词典
  if (SEMANTIC_PARAM_DICTIONARY[lower]) {
    const item = SEMANTIC_PARAM_DICTIONARY[lower]
    return {
      label: item.label,
      desc: item.desc,
      group: item.group,
      unit: item.unit || '',
      min: item.min ?? 1,
      max: item.max ?? 100,
      step: item.step ?? 1,
    }
  }

  let label = ''
  let desc = ''
  let group: StrategyParam['group'] = 'general'
  let unit = ''
  let min = 0
  let max = 100
  let step = 1

  // 2. 布尔开关类型处理 (如 enable_rsi_filter / use_trend_filter)
  const isBool = typeof val === 'boolean' || val === 'True' || val === 'False'
  if (isBool || lower.startsWith('enable_') || lower.startsWith('use_') || lower.startsWith('is_')) {
    const cleanWord = lower.replace(/^(enable_|use_|is_|apply_)/, '')
    if (cleanWord.includes('rsi')) {
      label = 'RSI 超买超卖过滤开关'
      desc = '开启后在市场极度过热时暂停追高买入，防范假突破套牢'
      group = 'buy'
    } else if (cleanWord.includes('trend')) {
      label = '多头顺势过滤保护开关'
      desc = '开启后仅在价格处于均线上方的多头格局中才允许开仓交易'
      group = 'buy'
    } else if (cleanWord.includes('stop') || cleanWord.includes('loss')) {
      label = '动态风控止损开关'
      desc = '开启后对持仓执行严格的最大回撤与止损保护，避免被动深套'
      group = 'sell'
    } else if (cleanWord.includes('profit') || cleanWord.includes('take')) {
      label = '阶段目标止盈开关'
      desc = '开启后在收益率达到预设目标时主动落袋为安'
      group = 'sell'
    } else if (cleanWord.includes('vol') || cleanWord.includes('volume')) {
      label = '成交量放量确认开关'
      desc = '开启后要求价格突破时必须伴随成交量放大确认才执行交易'
      group = 'buy'
    } else {
      label = `${cleanWord.replace(/_/g, ' ')} 策略开关`
      desc = '开启或关闭该策略特性的自动化决策逻辑'
    }
    return { label, desc, group, unit: '', min: 0, max: 1, step: 1 }
  }

  // 3. 判断分组 (group) 与基础单位
  if (
    lower.includes('buy') || lower.includes('entry') || lower.includes('bottom') ||
    lower.includes('dip') || lower.includes('fast') || lower.includes('low') ||
    lower.includes('oversold') || lower.includes('rebound')
  ) {
    group = 'buy'
  } else if (
    lower.includes('sell') || lower.includes('exit') || lower.includes('stop') ||
    lower.includes('profit') || lower.includes('slow') || lower.includes('overbought') ||
    lower.includes('loss') || lower.includes('high') || lower.includes('take')
  ) {
    group = 'sell'
  } else if (
    lower.includes('amount') || lower.includes('cash') || lower.includes('capital') ||
    lower.includes('pos') || lower.includes('weight') || lower.includes('share') ||
    lower.includes('size') || lower.includes('target') || lower.includes('base') ||
    lower.includes('ratio') || lower.includes('mult')
  ) {
    group = 'capital'
  }

  // 4. 底仓 base 复合词根处理 (彻底杜绝生硬拼接 "base 比例阈值")
  if (lower.includes('base')) {
    if (lower.includes('share') || lower.includes('lot')) {
      label = '网格单格买卖股数'
      desc = '触及网格上下轨时，单笔固定买卖的股票或ETF份数'
      unit = '股'
      min = 100; max = 5000; step = 100
    } else if (lower.includes('amount') || lower.includes('cash')) {
      label = '每期基准定投金额'
      desc = '每个定投周期固定的基础扣款金额（元），低估时可成倍追加'
      unit = '元'
      min = 500; max = 10000; step = 500
    } else {
      label = '初始底仓配置比例'
      desc = '策略初次启动时建立的基础底仓资金比例，保障持有打底筹码，避免空仓踏空'
      unit = '%'
      min = 0.10; max = 0.80; step = 0.05
    }
    return { label, desc, group: 'capital', unit, min, max, step }
  }

  // 5. 词根组合精细匹配专业中文人话标签与通俗解释
  if (lower.includes('bottom')) {
    if (lower.includes('window') || lower.includes('period') || lower.includes('days')) {
      label = '历史大底回溯周期'
      desc = '向前寻找极端历史大底的时间跨度（天），通常 250 天对应近一年大底'
      unit = '天'
      min = 60; max = 500; step = 10
    } else {
      label = '历史大底抄底买入分位'
      desc = '历史价格分位数低于该比例时认定处于极端大底黄金坑，触发低吸建仓'
      unit = '%'
      min = 0.05; max = 0.50; step = 0.05
    }
  } else if (lower.includes('dip')) {
    label = '极端暴跌抄底阈值'
    desc = '从阶段最高价回撤跌幅达该比例时果断重仓介入（如 15% 对应自高位急跌 15% 抄底）'
    unit = '%'
    min = 0.05; max = 0.40; step = 0.01
  } else if (lower.includes('rebound')) {
    if (lower.includes('bars') || lower.includes('days') || lower.includes('window')) {
      label = '触底反弹观察周期'
      desc = '触及大底后观察企稳反弹形态的连续交易天数窗口'
      unit = '天'
      min = 1; max = 20; step = 1
    } else {
      label = '触底反弹确认幅度'
      desc = '触底后从最低点回升达该幅度时确认反弹成立，启动右侧建仓'
      unit = '%'
      min = 0.01; max = 0.15; step = 0.005
    }
  } else if (lower.includes('stop') && (lower.includes('loss') || lower.includes('pct') || lower.includes('line'))) {
    label = '风控动态止损线'
    desc = '当单笔持仓浮亏触及该比例时坚决止损斩仓，防范本金灾难性亏损'
    unit = '%'
    min = 0.01; max = 0.20; step = 0.01
  } else if (lower.includes('profit') || lower.includes('take')) {
    if (lower.includes('ratio') || lower.includes('reduce')) {
      label = '高估止盈减仓比例'
      desc = '每次触发止盈信号时，从已有持仓中卖出变现的股份百分比（如减持 20%）'
    } else {
      label = '硬性止盈目标线'
      desc = '当持仓累计盈利达到该百分比时坚决落袋为安，避免利润坐过山车'
    }
    unit = '%'
    min = 0.05; max = 0.80; step = 0.05
  } else if (lower.includes('fast') && (lower.includes('period') || lower.includes('window') || lower.includes('ma'))) {
    label = '短期快均线周期'
    desc = '敏感跟踪短期价格变动，数值越小越灵敏，数值越大越平滑稳健'
    unit = '天'
    min = 2; max = 30; step = 1
  } else if (lower.includes('slow') && (lower.includes('period') || lower.includes('window') || lower.includes('ma'))) {
    label = '长期慢均线周期'
    desc = '平滑过滤短期杂波噪音，代表中长期趋势的基准方向'
    unit = '天'
    min = 10; max = 120; step = 5
  } else if (lower.includes('ma') && (lower.includes('period') || lower.includes('len') || lower.includes('window'))) {
    label = '均线计算周期'
    desc = '计算均线趋势所参考的历史交易天数'
    unit = '天'
    min = 5; max = 250; step = 5
  } else if (lower.includes('pos') || lower.includes('target')) {
    label = '开仓目标仓位比例'
    desc = '产生买入信号后，期望投资于该标的的资金占总资产的最大比例'
    unit = '%'
    min = 0.10; max = 1.0; step = 0.05
  } else if (lower.includes('window') || lower.includes('lookback') || lower.includes('period') || lower.includes('days')) {
    label = '历史计算回溯窗口'
    desc = '向前回溯计算技术指标所参考的历史天数长度'
    unit = '天'
    min = 10; max = 500; step = 10
  } else if (lower.includes('amount') || lower.includes('cash') || lower.includes('fund')) {
    label = '单笔基准资金金额'
    desc = '每次交易买入时的基准资金额度（元）'
    unit = '元'
    min = 500; max = 100000; step = 500
  } else if (lower.includes('share') || lower.includes('shares') || lower.includes('lot')) {
    label = '单笔交易基准股数'
    desc = '每次买卖交易委托的基础股票或ETF份数'
    unit = '股'
    min = 100; max = 10000; step = 100
  } else if (lower.includes('step') || lower.includes('grid')) {
    label = '网格间距波动比例'
    desc = '相邻两层网格之间的价格百分比间距，达到该波动自动高抛低吸'
    unit = '%'
    min = 0.01; max = 0.10; step = 0.005
  } else if (lower.includes('mult') || lower.includes('multiplier') || lower.includes('factor')) {
    label = '动态加倍系数'
    desc = '在触发加码条件时，将基准买入资金放大的倍数'
    unit = '倍'
    min = 1.0; max = 5.0; step = 0.5
  } else if (lower.includes('pct') || lower.includes('ratio') || lower.includes('rate') || lower.includes('weight') || lower.includes('band') || (typeof val === 'number' && val > 0 && val <= 1.0)) {
    const cleanWord = lower.replace(/_(pct|ratio|rate|weight|threshold|band)$/, '')
    label = cleanWord ? `${cleanWord.replace(/_/g, ' ')} 比例参数` : `${rawKey} 比例控制`
    desc = '用于控制策略触发买卖、仓位分配或风险防范的关键比例参数'
    unit = '%'
    min = 0.01; max = 1.0; step = 0.01
  } else {
    label = rawKey.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
    desc = '控制该量化策略运行机制的核心配置参数'
    unit = ''
    min = 1; max = 100; step = 1
  }

  return { label, desc, group, unit, min, max, step }
}

/**
 * 解析单个参数声明字符串与关联注释
 */
function parseParamToken(rawDecl: string, comment: string, paramsList: StrategyParam[]) {
  const clean = rawDecl.trim()
  if (!clean || clean === 'self' || clean.startsWith('*')) return

  const eqIdx = clean.indexOf('=')
  if (eqIdx === -1) return // 忽略无默认值的参数

  const left = clean.slice(0, eqIdx).trim()
  const right = clean.slice(eqIdx + 1).trim()

  let key = left
  let typeAnnotation = ''
  if (left.includes(':')) {
    const parts = left.split(':')
    key = parts[0].trim()
    typeAnnotation = parts[1].trim()
  }

  if (key === 'self' || key === 'args' || key === 'kwargs') return

  let defaultValue: any = right
  let inferredType: StrategyParam['type'] = 'float'

  if (right === 'True' || right === 'False') {
    defaultValue = right === 'True'
    inferredType = 'bool'
  } else if (/^-?\d+$/.test(right)) {
    defaultValue = parseInt(right, 10)
    inferredType = 'int'
  } else if (/^-?\d+\.\d+$/.test(right)) {
    defaultValue = parseFloat(right)
    inferredType = defaultValue > 0 && defaultValue <= 1.0 ? 'percent' : 'float'
  } else if (right.startsWith('"') || right.startsWith("'")) {
    defaultValue = right.slice(1, -1)
    inferredType = 'select'
  }

  // 1. 优先查阅静态字典与深度量化词根推断
  const lowerKey = key.toLowerCase()
  const semantic = SEMANTIC_PARAM_DICTIONARY[lowerKey] || inferQuantSemanticByKey(key, defaultValue)

  let label = semantic.label
  let group = semantic.group
  let unit = semantic.unit || ''
  let min = semantic.min ?? (inferredType === 'percent' ? 0.01 : 1)
  let max = semantic.max ?? (inferredType === 'percent' ? 1.0 : 100)
  let step = semantic.step ?? (inferredType === 'percent' ? 0.01 : 1)
  let description = ''

  // 针对数值范围兜底推断
  if (inferredType === 'int') {
    if (min === undefined) min = 1
    if (max === undefined) max = Math.max(defaultValue * 3, 100)
    if (step === undefined) step = 1
  } else if (inferredType === 'percent') {
    if (min === undefined) min = 0.01
    if (max === undefined) max = 1.0
    if (step === undefined) step = 0.01
    unit = '%'
  } else if (inferredType === 'float') {
    if (defaultValue <= 5.0) {
      if (min === undefined) min = 0.1
      if (max === undefined) max = 10.0
      if (step === undefined) step = 0.1
    } else {
      if (min === undefined) min = 100
      if (max === undefined) max = Math.max(defaultValue * 5, 100000)
      if (step === undefined) step = 500
      if (!unit) unit = '元'
    }
  }

  // 2. 高级 @param 注解覆盖解析 或 普通行尾中文注释提取
  if (comment) {
    if (comment.includes('@param')) {
      const lMatch = comment.match(/label=["']([^"']+)["']/)
      if (lMatch) label = lMatch[1]

      const minMatch = comment.match(/min=([0-9.]+)/)
      if (minMatch) min = parseFloat(minMatch[1])

      const maxMatch = comment.match(/max=([0-9.]+)/)
      if (maxMatch) max = parseFloat(maxMatch[1])

      const stepMatch = comment.match(/step=([0-9.]+)/)
      if (stepMatch) step = parseFloat(stepMatch[1])

      const unitMatch = comment.match(/unit=["']([^"']*)["']/)
      if (unitMatch) unit = unitMatch[1]

      const gMatch = comment.match(/group=["']([^"']+)["']/)
      if (gMatch) group = gMatch[1] as any

      const descMatch = comment.match(/desc=["']([^"']+)["']/)
      if (descMatch) description = descMatch[1]
    } else {
      // 若带有普通中文注释，提取注释作为标签和说明
      const cleanComment = comment.replace(/^[：:\s-]+/, '').trim()
      if (cleanComment) {
        description = cleanComment
        // 若注释包含中文字符，优先提取作为中文标签
        if (/[\u4e00-\u9fa5]/.test(cleanComment)) {
          // 截取前 12 个字或第一个标点前的短语作为标签
          const shortLabel = cleanComment.split(/[,，;；(（]/)[0].trim()
          if (shortLabel && shortLabel.length <= 14) {
            label = shortLabel
          }
        }
      }
    }
  }

  const finalDesc = description || semantic.desc || ''

  paramsList.push({
    key,
    name: key,
    label,
    type: inferredType,
    value: defaultValue,
    defaultValue,
    min,
    max,
    step,
    unit,
    group,
    desc: finalDesc,
    description: finalDesc,
  })
}

// 常见非业务的 AI 修复/修补日志特征词
const NOISY_DOCSTRING_PREFIXES = [
  '移除', '修复', '改为', '修改', '优化', '更新', '修正', '消除', '解决',
  'fix', 'fixed', 'remove', 'removed', 'refactor', 'bug', 'patch', 'update', 'updated'
]

/**
 * 解析 Python 策略源码并提取元数据与参数列表
 */
export function parseStrategyCode(code: string): StrategyParsedInfo {
  if (!code || !code.trim()) {
    return {
      className: '',
      docstring: '',
      plainSummary: '暂未检测到有效策略类',
      summary: '暂未检测到有效策略类',
      rules: [],
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

  // 3. 生成白话总结与规则列表（智能过滤掉修复补丁日志行）
  const rawDocLines = docstring ? docstring.split('\n').map((l) => l.trim()).filter((l) => l.length > 0) : []
  
  // 过滤掉如“移除不存在的 self.bars...”等 AI 代码自愈留下的工程噪音
  const meaningfulLines = rawDocLines.filter((line) => {
    const lower = line.toLowerCase()
    const isNoisy = NOISY_DOCSTRING_PREFIXES.some((prefix) => lower.startsWith(prefix))
    return !isNoisy && !line.startsWith('-') && !line.startsWith('*') && !line.startsWith('•') && !/^\d+\./.test(line)
  })

  let plainSummary = ''
  if (meaningfulLines.length > 0) {
    plainSummary = meaningfulLines[0]
  } else {
    // 若全是修复日志或没有 docstring，根据类名语义生成专业概述
    const lowerCls = className.toLowerCase()
    if (lowerCls.includes('bottom') || className.includes('底')) {
      plainSummary = '历史大底估值识别与极值反弹抄底交易策略'
    } else if (lowerCls.includes('ma') || className.includes('均线')) {
      plainSummary = '经典均线趋势跟踪与动量突破交易策略'
    } else if (lowerCls.includes('dca') || className.includes('定投')) {
      plainSummary = '动态估值分位数权重智能定投交易策略'
    } else if (lowerCls.includes('grid') || className.includes('网格')) {
      plainSummary = '自适应价格波动通道高抛低吸网格套利策略'
    } else {
      plainSummary = `基于 ${className} 架构的自动化量化交易策略`
    }
  }

  if (plainSummary.endsWith('：') || plainSummary.endsWith(':')) {
    plainSummary = plainSummary.slice(0, -1)
  }

  // 提取具体规则列表
  const rules: string[] = []
  for (const l of rawDocLines) {
    if (l.startsWith('-') || l.startsWith('*') || l.startsWith('•') || /^\d+\./.test(l)) {
      const cleanRule = l.replace(/^[-*•\d.]+\s*/, '').trim()
      // 同样过滤掉包含“移除/修复”字样的修复项
      const isNoisyRule = NOISY_DOCSTRING_PREFIXES.some((prefix) => cleanRule.toLowerCase().startsWith(prefix))
      if (!isNoisyRule) {
        rules.push(cleanRule)
      }
    }
  }

  // 4. 定位 def __init__(self, ...):
  const initMatch = code.match(/def\s+__init__\s*\(\s*self\s*,?([\s\S]*?)\)\s*:/)
  const params: StrategyParam[] = []

  if (initMatch && initMatch[1]) {
    const rawParamsBlock = initMatch[1]
    const lines = rawParamsBlock.split('\n')

    let accumulatedCode = ''
    let accumulatedComment = ''

    for (let i = 0; i < lines.length; i++) {
      const rawLine = lines[i].trim()
      if (!rawLine) continue

      // 分离代码与注释
      let lineCode = rawLine
      let lineComment = ''
      const hashIdx = rawLine.indexOf('#')
      if (hashIdx !== -1) {
        lineCode = rawLine.slice(0, hashIdx).trim()
        lineComment = rawLine.slice(hashIdx + 1).trim()
      }

      if (!lineCode) continue // 纯注释行

      accumulatedCode = (accumulatedCode ? accumulatedCode + ' ' : '') + lineCode
      accumulatedComment = (accumulatedComment ? accumulatedComment + ' ' : '') + lineComment

      const tokens = splitByTopLevelComma(accumulatedCode)

      if (tokens.length > 1) {
        for (let j = 0; j < tokens.length - 1; j++) {
          parseParamToken(tokens[j], j === 0 ? accumulatedComment : '', params)
        }
        accumulatedCode = tokens[tokens.length - 1]
        if (!accumulatedCode) {
          accumulatedComment = ''
        }
      }
    }

    if (accumulatedCode.trim()) {
      const remainingTokens = splitByTopLevelComma(accumulatedCode)
      for (const tok of remainingTokens) {
        if (tok.trim()) {
          parseParamToken(tok, accumulatedComment, params)
        }
      }
    }
  }

  return {
    className,
    docstring,
    plainSummary,
    summary: plainSummary,
    rules,
    params,
  }
}

export const parseStrategyParams = parseStrategyCode

/**
 * 精准替换 Python 源码中 __init__ 的指定参数默认值 (保持缩进与注释完全不变)
 */
export function updateCodeParam(code: string, paramKey: string, newValue: any): string {
  if (!code || !paramKey) return code

  let formattedVal = String(newValue)
  if (typeof newValue === 'boolean') {
    formattedVal = newValue ? 'True' : 'False'
  } else if (typeof newValue === 'number') {
    formattedVal = Number.isInteger(newValue) ? String(newValue) : String(Number(newValue.toFixed(4)))
  } else if (typeof newValue === 'string') {
    formattedVal = `"${newValue}"`
  }

  const initRegex = /(def\s+__init__\s*\([\s\S]*?\)\s*:)/
  const match = code.match(initRegex)
  if (!match) return code

  const initBlock = match[1]
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
