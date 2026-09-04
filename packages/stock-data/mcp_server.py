"""
========================================================================================
Global Stock Data - Model Context Protocol (MCP) Server
面向 Claude Desktop, Cursor, Antigravity 及各类 AI Agent 的金融智能数据工具集
通过标准 Stdio / SSE 协议提供 100% 真实金融数据支撑 (A股支持披露日严格 PIT，海外财报提供报告期估算)。
========================================================================================
"""

import json
import httpx
from typing import Optional
from mcp.server.mcpserver import MCPServer
from service.app import app

# 初始化 MCP 服务端
mcp = MCPServer("global-stock-data-mcp")

async def _call_api(endpoint: str, params: dict = None) -> str:
    """通过内存级 ASGI 极速直通 FastAPI，复用所有校验、复权与 SingleFlight 防御"""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://local") as client:
        try:
            resp = await client.get(endpoint, params=params)
            if resp.status_code == 200:
                return json.dumps(resp.json(), ensure_ascii=False, indent=2)
            else:
                return json.dumps({"error": f"HTTP {resp.status_code}", "detail": resp.text}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": "Internal execution error", "detail": str(e)}, ensure_ascii=False)

@mcp.tool()
async def get_stock_kline(
    symbol: str,
    period: str = "1d",
    start: Optional[str] = None,
    end: Optional[str] = None,
    adjust: str = "qfq",
    indicators: Optional[str] = None
) -> str:
    """
    获取股票、ETF 或宽基指数的高精度 K 线行情走势。
    :param symbol: 标的代码，支持简写自动推断 (如 002594, 600519, 510300, QQQ, AAPL)
    :param period: K线周期: 1m, 5m, 15m, 30m, 60m, 1d (默认 1d)
    :param start: 起始日期 YYYY-MM-DD (默认最近1年)
    :param end: 截止日期 YYYY-MM-DD (默认当天)
    :param adjust: 复权方式: raw(不复权), qfq(前复权, 推荐), hfq(后复权)
    :param indicators: 可选追加量化技术指标，逗号分隔，如: MA,MACD,RSI,BOLL,ATR,ALL
    """
    params = {"symbol": symbol, "period": period, "adjust": adjust}
    if start: params["start"] = start
    if end: params["end"] = end
    if indicators: params["indicators"] = indicators
    return await _call_api("/api/v1/kline", params)

@mcp.tool()
async def get_stock_valuation(symbol: str) -> str:
    """
    获取个股或 ETF 的实时基本面估值指标:
    包括滚动市盈率 PE(TTM)、前瞻市盈率 Forward PE、市净率 PB、总市值、股息率以及近1年历史估值走势分位。
    :param symbol: 股票代码，如 002594 (比亚迪), 600519 (茅台), AAPL (苹果)
    """
    return await _call_api("/api/v1/stock/valuation", {"symbol": symbol})

@mcp.tool()
async def get_stock_financials(symbol: str) -> str:
    """
    获取上市公司深度财务三大报表核心摘要 (资产负债表、利润表、现金流量表):
    包含营业收入、净利润、销售毛利率、资产负债率。A 股支持基于真实官方披露日 (announcement_date) 的严格 PIT 过滤；海外财报因源端缺少可靠历史公告时间戳，标记为估算 (ESTIMATED)。
    :param symbol: 股票代码，如 002594, 600519, AAPL
    """
    return await _call_api("/api/v1/stock/financials", {"symbol": symbol})

@mcp.tool()
async def get_stock_profile(symbol: str) -> str:
    """
    获取上市公司官方画像、行业分类与主营业务:
    包括所属申万/证监会行业门类、主要业务范围、上市日期、注册资本与机构简介。
    :param symbol: 股票代码，如 002594, 600519, AAPL
    """
    return await _call_api("/api/v1/stock/profile", {"symbol": symbol})

@mcp.tool()
async def get_stock_shareholders(symbol: str) -> str:
    """
    获取股东户数（筹码集中度）与十大流通股东持股占比:
    用于判断散户交筹码、机构建仓趋势，返回最新报告期股东总数、户均持股数与前十大股东名单明细。
    :param symbol: 股票代码，如 002594, 600519
    """
    return await _call_api("/api/v1/stock/shareholders", {"symbol": symbol})

@mcp.tool()
async def get_market_sectors(indicator: str = "行业", limit: int = 15) -> str:
    """
    获取全市场行业板块或概念题材板块的最新涨跌幅排名与领涨龙头股。
    :param indicator: 板块类型: '行业' 或 '概念' (如光伏、低空经济、算力等概念题材)
    :param limit: 返回前 N 个领涨板块 (默认 15)
    """
    return await _call_api("/api/v1/market/sectors", {"indicator": indicator, "limit": limit})

@mcp.tool()
async def get_dragon_tiger_list(date: Optional[str] = None) -> str:
    """
    获取每日交易所龙虎榜上榜异动股票明细:
    包含机构专用席位、知名游资营业部打板买卖金额、涨跌幅偏离值与上榜原因。
    :param date: 指定交易日期 YYYYMMDD (如 20240115)，留空默认今日最新
    """
    params = {}
    if date: params["date"] = date
    return await _call_api("/api/v1/market/dragon-tiger", params)

@mcp.tool()
async def screen_stocks(
    min_pct_change: Optional[float] = None,
    max_pct_change: Optional[float] = None,
    min_amount: Optional[float] = None,
    limit: int = 15
) -> str:
    """
    A 股 5000+ 股票每日截面选股器 (A-Share Screener):
    支持按今日涨跌幅区间、成交额下限过滤出高流动性强势股。
    :param min_pct_change: 最小涨幅百分比，如 5.0 表示涨幅 >= 5%
    :param max_pct_change: 最大涨幅百分比，如 10.0
    :param min_amount: 最低成交额 (单位: 元)，如 500000000 表示成交额 >= 5 亿
    :param limit: 返回数量上限 (默认 15)
    """
    params = {"limit": limit}
    if min_pct_change is not None: params["min_pct_change"] = min_pct_change
    if max_pct_change is not None: params["max_pct_change"] = max_pct_change
    if min_amount is not None: params["min_amount"] = min_amount
    return await _call_api("/api/v1/screener", params)

@mcp.tool()
async def get_macro_treasury_yield() -> str:
    """
    获取中美 10 年期国债最新基准收益率 (无风险利率):
    用于资产估值模型 (DCF 折现率) 与大类资产股债轮动研判。
    """
    return await _call_api("/api/v1/macro/treasury-yield")

@mcp.tool()
async def get_system_storage_status() -> str:
    """
    获取本地数据中台的存储预算水位 (50GB 存储/缓存安全预算) 与系统健康状态。
    """
    return await _call_api("/api/v1/system/storage")

if __name__ == "__main__":
    # 以标准 stdio 模式启动供 Claude Desktop / Cursor 连接
    mcp.run()
