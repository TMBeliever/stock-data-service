/**
 * 纯 TS 图表规格工厂：输入结构化数据，输出 ECharts option 规格对象。
 * 纯函数、零 DOM 依赖、零 ECharts 运行时依赖（在 Node/浏览器/小程序环境均可测试）。
 */

export interface ChartSpec {
  type: 'gauge' | 'line' | 'kline'
  /** ECharts 兼容的 option 子集，字段与渲染器解耦 */
  option: Record<string, unknown>
}

/** 温度档位：0-30 冷(绿) 30-70 中性(琥珀) 70-100 热(红) —— A股语义：低估=机会 */
export function temperatureColor(value: number): string {
  if (value < 30) return '#30d4a4'
  if (value < 70) return '#ffb340'
  return '#ff2d55'
}

export function temperatureGaugeSpec(temperature: number, label: string): ChartSpec {
  const color = temperatureColor(temperature)
  return {
    type: 'gauge',
    option: {
      series: [
        {
          type: 'gauge',
          min: 0,
          max: 100,
          startAngle: 210,
          endAngle: -30,
          progress: { show: true, width: 14, itemStyle: { color } },
          axisLine: { lineStyle: { width: 14, color: [[1, 'rgba(255,255,255,0.08)']] } },
          axisTick: { show: false },
          splitLine: { show: false },
          axisLabel: { show: false },
          pointer: { show: false },
          anchor: { show: false },
          detail: {
            valueAnimation: true,
            offsetCenter: [0, '10%'],
            formatter: '{value}',
            fontSize: 40,
            fontWeight: 700,
            color,
          },
          data: [{ value: Math.round(temperature * 10) / 10, name: label }],
          title: { offsetCenter: [0, '45%'], fontSize: 13, color: 'rgba(255,255,255,0.55)' },
        },
      ],
    },
  }
}

/** 估值 20 年历史时序多轴图表构建器 (PE/PB 双轴) */
export function buildValuationChartOption(data: {
  indexName?: string
  dates: string[]
  pe: number[]
  pb: number[]
}): Record<string, unknown> {
  const darkText = 'rgba(255,255,255,0.45)'
  return {
    backgroundColor: 'transparent',
    grid: { left: 45, right: 45, top: 32, bottom: 30 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(18, 18, 22, 0.95)',
      borderColor: 'rgba(255, 255, 255, 0.12)',
      textStyle: { color: '#f4f4f6', fontSize: 12 },
    },
    legend: {
      data: ['市盈率 PE', '市净率 PB'],
      textStyle: { color: darkText, fontSize: 11 },
      top: 0,
      right: 10,
    },
    xAxis: {
      type: 'category',
      data: data.dates,
      axisLabel: { color: darkText, fontSize: 10 },
      axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } },
    },
    yAxis: [
      {
        type: 'value',
        name: 'PE',
        nameTextStyle: { color: darkText, fontSize: 10 },
        scale: true,
        axisLabel: { color: darkText, fontSize: 10 },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
      },
      {
        type: 'value',
        name: 'PB',
        nameTextStyle: { color: darkText, fontSize: 10 },
        scale: true,
        axisLabel: { color: darkText, fontSize: 10 },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '市盈率 PE',
        type: 'line',
        yAxisIndex: 0,
        data: data.pe,
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2, color: '#ff5f3d' },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(255, 95, 61, 0.2)' },
              { offset: 1, color: 'rgba(255, 95, 61, 0.0)' },
            ],
          },
        },
      },
      {
        name: '市净率 PB',
        type: 'line',
        yAxisIndex: 1,
        data: data.pb,
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 1.5, color: '#8b5cf6' },
      },
    ],
  }
}

export function percentileLineSpec(
  points: { date: string; value: number }[],
  name: string,
): ChartSpec {
  return {
    type: 'line',
    option: {
      grid: { left: 40, right: 16, top: 24, bottom: 28 },
      xAxis: { type: 'category', data: points.map((p) => p.date) },
      yAxis: { type: 'value', min: 0, max: 100 },
      tooltip: { trigger: 'axis' },
      series: [
        {
          name,
          type: 'line',
          smooth: true,
          symbol: 'none',
          data: points.map((p) => p.value),
          areaStyle: { opacity: 0.15 },
          lineStyle: { width: 2 },
        },
      ],
    },
  }
}

/** 机构级专业 K 线图构建器 (支持日K/周K/月K/年K + MA5/10/20/60 + 成交量，全中文标注) */
export function buildCandlestickChartOption(data: {
  name: string
  bars: {
    date: string
    open: number
    close: number
    high: number
    low: number
    volume: number
    ma5?: number
    ma10?: number
    ma20?: number
    ma60?: number
  }[]
}): Record<string, unknown> {
  const darkText = 'rgba(255,255,255,0.45)'
  const dates = data.bars.map((b) => b.date)
  const ohlc = data.bars.map((b) => [b.open, b.close, b.low, b.high])
  const volumes = data.bars.map((b) => ({
    value: b.volume,
    itemStyle: {
      color: b.close >= b.open ? 'rgba(255, 77, 79, 0.8)' : 'rgba(34, 197, 94, 0.8)',
    },
  }))

  return {
    backgroundColor: 'transparent',
    animation: false,
    grid: [
      { left: 52, right: 24, top: 32, height: '58%' },
      { left: 52, right: 24, top: '74%', height: '16%' },
    ],
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', lineStyle: { color: 'rgba(255,255,255,0.2)' } },
      backgroundColor: 'rgba(18, 18, 22, 0.95)',
      borderColor: 'rgba(255, 255, 255, 0.12)',
      textStyle: { color: '#f4f4f6', fontSize: 12 },
      formatter: (params: any) => {
        if (!Array.isArray(params) || params.length === 0) return ''
        const dateStr = params[0].axisValue
        let html = `<div style="font-weight:bold;margin-bottom:6px;color:#fff;">${dateStr}</div>`

        for (const item of params) {
          if (item.seriesType === 'candlestick') {
            const raw = item.data
            const o = Number(raw[1] || 0)
            const c = Number(raw[2] || 0)
            const l = Number(raw[3] || 0)
            const h = Number(raw[4] || 0)
            const chgPct = o > 0 ? ((c - o) / o) * 100 : 0
            const color = c >= o ? '#ff4d4f' : '#22c55e'
            html += `
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px 16px;color:#d4d4d8;font-size:11px;margin-bottom:6px;">
                <div>开盘: <b style="color:${color}">${o.toFixed(2)}</b></div>
                <div>最高: <b style="color:${color}">${h.toFixed(2)}</b></div>
                <div>收盘: <b style="color:${color}">${c.toFixed(2)} (${chgPct >= 0 ? '+' : ''}${chgPct.toFixed(2)}%)</b></div>
                <div>最低: <b style="color:${color}">${l.toFixed(2)}</b></div>
              </div>
            `
          } else if (item.seriesName.includes('MA') || item.seriesName.includes('均线')) {
            html += `
              <div style="display:flex;justify-content:space-between;gap:12px;font-size:11px;line-height:1.4;">
                <span style="color:${item.color}">${item.seriesName}:</span>
                <span style="font-weight:bold;color:#fff">${Number(item.data).toFixed(2)}</span>
              </div>
            `
          } else if (item.seriesName === '成交量') {
            const v = Number(item.data?.value ?? item.data)
            const vStr = v >= 10000 ? `${(v / 10000).toFixed(2)} 万手` : `${v} 手`
            html += `
              <div style="display:flex;justify-content:space-between;gap:12px;margin-top:4px;border-top:1px solid rgba(255,255,255,0.08);padding-top:4px;font-size:11px;">
                <span style="color:#a1a1aa">成交量:</span>
                <span style="font-weight:bold;color:#fff">${vStr}</span>
              </div>
            `
          }
        }
        return html
      },
    },
    legend: {
      data: ['K线', '5日均线 (MA5)', '10日均线 (MA10)', '20日均线 (MA20)', '60日均线 (MA60)'],
      textStyle: { color: darkText, fontSize: 11 },
      top: 4,
      right: 12,
    },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    dataZoom: [
      {
        type: 'inside',
        xAxisIndex: [0, 1],
        start: Math.max(0, 100 - (60 / (dates.length || 1)) * 100),
        end: 100,
      },
    ],
    xAxis: [
      {
        type: 'category',
        data: dates,
        gridIndex: 0,
        axisLabel: { color: darkText, fontSize: 10 },
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } },
      },
      {
        type: 'category',
        data: dates,
        gridIndex: 1,
        axisLabel: { show: false },
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } },
      },
    ],
    yAxis: [
      {
        type: 'value',
        gridIndex: 0,
        scale: true,
        axisLabel: { color: darkText, fontSize: 10 },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
      },
      {
        type: 'value',
        gridIndex: 1,
        scale: true,
        axisLabel: { show: false },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        data: ohlc,
        itemStyle: {
          color: '#ff4d4f',
          color0: '#22c55e',
          borderColor: '#ff4d4f',
          borderColor0: '#22c55e',
        },
      },
      {
        name: '5日均线 (MA5)',
        type: 'line',
        data: data.bars.map((b) => b.ma5 ?? b.close),
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 1.2, color: '#f59e0b' },
      },
      {
        name: '10日均线 (MA10)',
        type: 'line',
        data: data.bars.map((b) => b.ma10 ?? b.close),
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 1.2, color: '#a855f7' },
      },
      {
        name: '20日均线 (MA20)',
        type: 'line',
        data: data.bars.map((b) => b.ma20 ?? b.close),
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 1.2, color: '#3b82f6' },
      },
      {
        name: '60日均线 (MA60)',
        type: 'line',
        data: data.bars.map((b) => b.ma60 ?? b.close),
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 1.2, color: '#10b981' },
      },
      {
        name: '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: volumes,
      },
    ],
  }
}

/** 专业分时图构建器 (分时价格线 + 均价线 + 昨收基准线 + 分时量能，全中文标注) */
export function buildMinuteTimelineChartOption(data: {
  name: string
  prevClose: number
  points: { time: string; price: number; volume: number }[]
}): Record<string, unknown> {
  const darkText = 'rgba(255,255,255,0.45)'
  const times = data.points.map((p) => p.time)
  const prices = data.points.map((p) => p.price)
  const volumes = data.points.map((p) => ({
    value: p.volume,
    itemStyle: {
      color: p.price >= data.prevClose ? 'rgba(255, 77, 79, 0.8)' : 'rgba(34, 197, 94, 0.8)',
    },
  }))

  return {
    backgroundColor: 'transparent',
    animation: false,
    grid: [
      { left: 52, right: 24, top: 28, height: '58%' },
      { left: 52, right: 24, top: '74%', height: '16%' },
    ],
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', lineStyle: { color: 'rgba(255,255,255,0.2)' } },
      backgroundColor: 'rgba(18, 18, 22, 0.95)',
      borderColor: 'rgba(255, 255, 255, 0.12)',
      textStyle: { color: '#f4f4f6', fontSize: 12 },
      formatter: (params: any) => {
        if (!Array.isArray(params) || params.length === 0) return ''
        const timeStr = params[0].axisValue
        let html = `<div style="font-weight:bold;margin-bottom:4px;color:#fff;">时间: ${timeStr}</div>`

        for (const item of params) {
          if (item.seriesName === '分时现价') {
            const p = Number(item.data)
            const chg = data.prevClose ? p - data.prevClose : 0
            const chgPct = data.prevClose ? (chg / data.prevClose) * 100 : 0
            const color = chg >= 0 ? '#ff4d4f' : '#22c55e'
            html += `
              <div style="display:flex;justify-content:space-between;gap:12px;font-size:11px;">
                <span style="color:#a1a1aa">现价:</span>
                <b style="color:${color}">${p.toFixed(2)} (${chg >= 0 ? '+' : ''}${chgPct.toFixed(2)}%)</b>
              </div>
            `
          } else if (item.seriesName === '分时成交量') {
            const v = Number(item.data?.value ?? item.data)
            html += `
              <div style="display:flex;justify-content:space-between;gap:12px;margin-top:2px;font-size:11px;">
                <span style="color:#a1a1aa">成交量:</span>
                <b style="color:#fff">${v} 手</b>
              </div>
            `
          }
        }
        return html
      },
    },
    xAxis: [
      {
        type: 'category',
        data: times,
        gridIndex: 0,
        axisLabel: { color: darkText, fontSize: 10 },
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } },
      },
      {
        type: 'category',
        data: times,
        gridIndex: 1,
        axisLabel: { show: false },
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } },
      },
    ],
    yAxis: [
      {
        type: 'value',
        gridIndex: 0,
        scale: true,
        axisLabel: { color: darkText, fontSize: 10 },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
      },
      {
        type: 'value',
        gridIndex: 1,
        scale: true,
        axisLabel: { show: false },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '分时现价',
        type: 'line',
        data: prices,
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 1.8, color: '#ff5f3d' },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(255, 95, 61, 0.25)' },
              { offset: 1, color: 'rgba(255, 95, 61, 0.0)' },
            ],
          },
        },
        markLine: data.prevClose
          ? {
              symbol: 'none',
              lineStyle: { type: 'dashed', color: 'rgba(255,255,255,0.3)', width: 1 },
              data: [{ yAxis: data.prevClose, label: { formatter: '昨收基准', color: darkText } }],
            }
          : undefined,
      },
      {
        name: '分时成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: volumes,
      },
    ],
  }
}

/** 收盘价 + MA20 双线图（日K简化版） */
export function klineSpec(
  bars: { date: string; close: number; ma20: number }[],
  name: string,
): ChartSpec {
  const darkText = 'rgba(255,255,255,0.55)'
  return {
    type: 'line',
    option: {
      grid: { left: 52, right: 16, top: 24, bottom: 28 },
      xAxis: {
        type: 'category',
        data: bars.map((b) => b.date),
        axisLabel: { color: darkText, fontSize: 10 },
      },
      yAxis: {
        type: 'value',
        scale: true,
        axisLabel: { color: darkText, fontSize: 10 },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
      },
      tooltip: { trigger: 'axis' },
      series: [
        {
          name,
          type: 'line',
          symbol: 'none',
          data: bars.map((b) => b.close),
          lineStyle: { width: 1.6, color: '#ff5f3d' },
        },
        {
          name: 'MA20',
          type: 'line',
          symbol: 'none',
          data: bars.map((b) => b.ma20),
          lineStyle: { width: 1.2, color: '#f59e0b', opacity: 0.8 },
        },
      ],
      legend: { textStyle: { color: darkText }, top: 0, right: 0 },
    },
  }
}

/** 宏观指标多线图 */
export function macroLinesSpec(
  seriesMap: Record<string, { date: string; value: number }[]>,
): ChartSpec {
  const colors = ['#ff5f3d', '#ff2d55', '#f59e0b', '#22c55e', '#ef4444']
  const keys = Object.keys(seriesMap)
  const darkText = 'rgba(255,255,255,0.55)'
  const firstSeries: { date: string; value: number }[] = keys[0] ? (seriesMap[keys[0]] ?? []) : []
  return {
    type: 'line',
    option: {
      grid: { left: 56, right: 16, top: 36, bottom: 28 },
      tooltip: { trigger: 'axis' },
      legend: { textStyle: { color: darkText }, top: 0 },
      xAxis: {
        type: 'category',
        data: firstSeries.map((p) => p.date),
        axisLabel: { color: darkText, fontSize: 10 },
      },
      yAxis: {
        type: 'value',
        scale: true,
        axisLabel: { color: darkText, fontSize: 10, formatter: (v: number) => v.toFixed(2) },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
      },
      series: keys.map((k, i) => ({
        name: k,
        type: 'line',
        symbol: 'none',
        data: (seriesMap[k] ?? []).map((p: { date: string; value: number }) => p.value),
        lineStyle: { width: 1.5, color: colors[i % colors.length] },
      })),
    },
  }
}

/** 配置占比环形图 */
export function allocationDonutSpec(alloc: Record<string, number>): ChartSpec {
  const labels: Record<string, string> = {
    equity: '股票',
    bond: '债券',
    cash: '现金',
    gold: '黄金',
  }
  const palette: Record<string, string> = {
    equity: '#ef4444',
    bond: '#ff5f3d',
    cash: '#6b7280',
    gold: '#f59e0b',
  }
  return {
    type: 'gauge',
    option: {
      tooltip: { trigger: 'item' },
      legend: { bottom: 0, textStyle: { color: 'rgba(255,255,255,0.55)' } },
      series: [
        {
          type: 'pie',
          radius: ['55%', '80%'],
          center: ['50%', '45%'],
          label: { show: false },
          data: Object.entries(alloc)
            .filter(([k]) => k in labels)
            .map(([k, v]) => ({
              name: labels[k],
              value: v,
              itemStyle: { color: palette[k] ?? '#6b7280' },
            })),
        },
      ],
    },
  }
}

/** 温度历史曲线：带冷/热区背景带与阈值线 */
export function temperatureHistorySpec(
  points: { date: string; value: number }[],
  name = '温度',
): ChartSpec {
  const darkText = 'rgba(255,255,255,0.55)'
  return {
    type: 'line',
    option: {
      grid: { left: 40, right: 16, top: 24, bottom: 28 },
      xAxis: {
        type: 'category',
        data: points.map((p) => p.date),
        axisLabel: { color: darkText, fontSize: 10 },
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: 100,
        axisLabel: { color: darkText, fontSize: 10 },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
      },
      tooltip: { trigger: 'axis' },
      series: [
        {
          name,
          type: 'line',
          smooth: true,
          symbol: 'none',
          data: points.map((p) => p.value),
          lineStyle: { width: 2, color: '#ff2d55' },
          areaStyle: {
            opacity: 1,
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(255,45,85,0.25)' },
                { offset: 0.5, color: 'rgba(255,179,64,0.14)' },
                { offset: 1, color: 'rgba(48,212,164,0.25)' },
              ],
            },
          },
          markLine: {
            silent: true,
            symbol: 'none',
            label: { show: false },
            lineStyle: { type: 'dashed', opacity: 0.4 },
            data: [{ yAxis: 30 }, { yAxis: 70 }],
          },
        },
      ],
    },
  }
}

/** 回测统计条形图：冷/中性/热占比 */
export function zoneDistributionSpec(summary: {
  cold_ratio?: number
  hot_ratio?: number
}): ChartSpec {
  const cold = summary.cold_ratio ?? 0
  const hot = summary.hot_ratio ?? 0
  const neutral = Math.max(0, 100 - cold - hot)
  return {
    type: 'gauge',
    option: {
      xAxis: { type: 'category', data: ['低温(机会)', '中性', '高温(过热)'] },
      yAxis: { type: 'value', max: 100, axisLabel: { formatter: '{value}%' } },
      tooltip: { trigger: 'axis' },
      series: [
        {
          type: 'bar',
          data: [
            { value: cold, itemStyle: { color: '#22c55e' } },
            { value: neutral, itemStyle: { color: '#f59e0b' } },
            { value: hot, itemStyle: { color: '#ef4444' } },
          ],
          barWidth: '55%',
          label: { show: true, position: 'top', formatter: '{c}%' },
        },
      ],
    },
  }
}

/** 量化策略净值时序与基准对比走势图规格工厂 */
export function buildBacktestNavChartOption(navSeries: Array<{
  date: string
  nav: number
  benchmark_nav: number
}>): Record<string, unknown> {
  const dates = navSeries.map((d) => d.date)
  const stratData = navSeries.map((d) => Math.round((d.nav - 1.0) * 10000) / 100)
  const bmData = navSeries.map((d) => Math.round((d.benchmark_nav - 1.0) * 10000) / 100)

  const darkText = 'rgba(255,255,255,0.45)'

  return {
    backgroundColor: 'transparent',
    grid: { left: 55, right: 25, top: 35, bottom: 45 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(18, 18, 22, 0.95)',
      borderColor: 'rgba(255, 255, 255, 0.12)',
      textStyle: { color: '#f4f4f6', fontSize: 12 },
      formatter: (params: any) => {
        if (!Array.isArray(params) || params.length === 0) return ''
        const dateStr = params[0].axisValue
        let html = `<div class="font-bold text-zinc-300 pb-1 border-b border-white/10 mb-1">${dateStr}</div>`
        params.forEach((p: any) => {
          const val = p.value
          const color = val >= 0 ? '#ef4444' : '#22c55e'
          html += `<div class="flex items-center justify-between space-x-4 py-0.5">
            <span class="text-zinc-400">${p.marker} ${p.seriesName}:</span>
            <span class="font-mono font-bold" style="color:${color}">${val >= 0 ? '+' : ''}${val.toFixed(2)}%</span>
          </div>`
        })
        return html
      },
    },
    legend: {
      data: ['策略累计收益', '基准(沪深300)'],
      textStyle: { color: darkText, fontSize: 11 },
      top: 0,
      right: 15,
    },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: { color: darkText, fontSize: 10 },
      axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } },
    },
    yAxis: {
      type: 'value',
      name: '累计收益率 (%)',
      nameTextStyle: { color: darkText, fontSize: 10 },
      scale: true,
      axisLabel: {
        color: darkText,
        fontSize: 10,
        formatter: '{value}%',
      },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
    },
    series: [
      {
        name: '策略累计收益',
        type: 'line',
        data: stratData,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2.5, color: '#f59e0b' },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(245, 158, 11, 0.25)' },
              { offset: 1, color: 'rgba(245, 158, 11, 0.0)' },
            ],
          },
        },
      },
      {
        name: '基准(沪深300)',
        type: 'line',
        data: bmData,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 1.5, color: '#38bdf8', type: 'dashed' },
      },
    ],
  }
}

