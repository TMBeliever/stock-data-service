"""
stock_data.py — 金融行情数据工具组
将 stock-data 服务的 REST API 包装为 MCP 工具，供 quant-agent 通过 MCP 协议调用。
所有工具均通过 HTTP 调用 stock-data FastAPI，不直连数据库。
"""
import json
import logging
from typing import Optional
import httpx

from mcp.server.mcpserver import MCPServer
from mcp_gateway.config import gateway_config

logger = logging.getLogger(__name__)

# 复用连接池，避免每次工具调用重建连接
_http_client: Optional[httpx.AsyncClient] = None


def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            base_url=gateway_config.STOCK_DATA_URL,
            timeout=30.0,
            headers={"X-Internal-Service": gateway_config.INTERNAL_SERVICE_NAME}
        )
    return _http_client


async def _call(endpoint: str, params: dict = None) -> str:
    """调用 stock-data REST API，统一错误处理"""
    try:
        resp = await get_http_client().get(endpoint, params=params or {})
        if resp.status_code == 200:
            return json.dumps(resp.json(), ensure_ascii=False, indent=2)
        return json.dumps(
            {"error": f"HTTP {resp.status_code}", "detail": resp.text},
            ensure_ascii=False
        )
    except Exception as e:
        logger.error("stock-data call failed [%s]: %s", endpoint, e)
        return json.dumps({"error": "stock-data 服务不可用", "detail": str(e)}, ensure_ascii=False)


def register_stock_tools(mcp: MCPServer) -> None:
    """将所有金融行情工具注册到 MCP 服务端"""

    @mcp.tool()
    async def get_realtime_quote(symbol: str) -> str:
        """
        【首选核心报价工具】获取单只或多只股票/ETF/指数的最新实时行情报价快照 (Quote / Snapshot)。
        包含最新成交价 (latest_price)、今日涨跌额/涨跌幅 (change / pct_change)、昨收价 (pre_close)、
        今开 (open)、最高最低 (high/low)、成交量额 (volume/amount)、换手率 (turnover_rate)、
        市盈率 PE(TTM)、市净率 PB、总市值 (total_market_cap)、股息率以及买卖五档盘口。
        【重要】当用户询问股票"当前价格/最新股价/今天涨跌/实时行情/盘口/详情"时，必须优先调用此工具！
        :param symbol: 标的代码，支持简写自动推断 (如 600519, 002594, 510300, AAPL)
        """
        return await _call("/api/v1/snapshot", {"symbols": symbol})

    @mcp.tool()
    async def get_stock_kline(
        symbol: str,
        period: str = "1d",
        start: Optional[str] = None,
        end: Optional[str] = None,
        adjust: str = "qfq",
        indicators: Optional[str] = None,
        limit: Optional[int] = 30
    ) -> str:
        """
        获取股票、ETF 或宽基指数的高精度历史 K 线走势与量化技术指标。
        【注意】仅在分析走势形态、技术均线、MACD/BOLL/RSI 等历史序列时调用；若仅查询当前最新股价，请调用 get_realtime_quote。
        用户未指定时间时，默认截止到当前最新交易日，默认返回最近 30 根 K 线柱。
        :param symbol: 标的代码，支持简写自动推断 (如 002594, 600519, 510300, QQQ, AAPL)
        :param period: K线周期: 1m, 5m, 15m, 30m, 60m, 1d (默认 1d)
        :param start: 起始日期 YYYY-MM-DD
        :param end: 截止日期 YYYY-MM-DD (未指定时默认为当前最新交易日)
        :param adjust: 复权方式: raw(不复权), qfq(前复权, 推荐), hfq(后复权)
        :param indicators: 可选追加量化技术指标，逗号分隔，如: MA,MACD,RSI,BOLL,ATR,ALL
        :param limit: 返回的最大 K 线柱数限制 (默认返回最近 30 根)
        """
        params = {"symbol": symbol, "period": period, "adjust": adjust}
        if start: params["start"] = start
        if end: params["end"] = end
        if indicators: params["indicators"] = indicators
        if limit is not None: params["limit"] = limit
        return await _call("/api/v1/kline", params)

    @mcp.tool()
    async def get_stock_valuation(symbol: str) -> str:
        """
        获取个股或 ETF 的实时基本面估值指标：
        包括滚动市盈率 PE(TTM)、前瞻市盈率 Forward PE、市净率 PB、总市值、股息率以及近1年历史估值走势分位。
        :param symbol: 股票代码，如 002594 (比亚迪), 600519 (茅台), AAPL (苹果)
        """
        return await _call("/api/v1/stock/valuation", {"symbol": symbol})

    @mcp.tool()
    async def get_stock_financials(symbol: str) -> str:
        """
        获取上市公司深度财务三大报表核心摘要 (资产负债表、利润表、现金流量表)：
        包含营业收入、净利润、销售毛利率、资产负债率。A 股支持基于真实官方披露日的严格 PIT 过滤。
        :param symbol: 股票代码，如 002594, 600519, AAPL
        """
        return await _call("/api/v1/stock/financials", {"symbol": symbol})

    @mcp.tool()
    async def get_stock_profile(symbol: str) -> str:
        """
        获取上市公司官方画像、行业分类与主营业务：
        包括所属申万/证监会行业门类、主要业务范围、上市日期、注册资本与机构简介。
        :param symbol: 股票代码，如 002594, 600519, AAPL
        """
        return await _call("/api/v1/stock/profile", {"symbol": symbol})

    @mcp.tool()
    async def get_stock_shareholders(symbol: str) -> str:
        """
        获取股东户数（筹码集中度）与十大流通股东持股占比：
        用于判断散户交筹码、机构建仓趋势，返回最新报告期股东总数与前十大股东名单明细。
        :param symbol: 股票代码，如 002594, 600519
        """
        return await _call("/api/v1/stock/shareholders", {"symbol": symbol})

    @mcp.tool()
    async def get_market_sectors(indicator: str = "行业", limit: int = 15) -> str:
        """
        获取全市场行业板块或概念题材板块的最新涨跌幅排名与领涨龙头股。
        :param indicator: 板块类型: '行业' 或 '概念' (如光伏、低空经济、算力等概念题材)
        :param limit: 返回前 N 个领涨板块 (默认 15)
        """
        return await _call("/api/v1/market/sectors", {"indicator": indicator, "limit": limit})

    @mcp.tool()
    async def get_dragon_tiger_list(date: Optional[str] = None) -> str:
        """
        获取每日交易所龙虎榜上榜异动股票明细：
        包含机构专用席位、知名游资营业部打板买卖金额、涨跌幅偏离值与上榜原因。
        :param date: 指定交易日期 YYYYMMDD (如 20240115)，留空默认今日最新
        """
        params = {}
        if date: params["date"] = date
        return await _call("/api/v1/market/dragon-tiger", params)

    @mcp.tool()
    async def screen_stocks(
        min_pct_change: Optional[float] = None,
        max_pct_change: Optional[float] = None,
        min_amount: Optional[float] = None,
        limit: int = 15
    ) -> str:
        """
        A 股 5000+ 股票每日截面选股器 (A-Share Screener)：
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
        return await _call("/api/v1/screener", params)

    @mcp.tool()
    async def get_macro_treasury_yield() -> str:
        """
        获取中美 10 年期国债最新基准收益率 (无风险利率)：
        用于资产估值模型 (DCF 折现率) 与大类资产股债轮动研判。
        """
        return await _call("/api/v1/macro/treasury-yield")

    @mcp.tool()
    async def get_system_storage_status() -> str:
        """获取本地金融数据中台的存储预算水位与系统健康状态。"""
        return await _call("/api/v1/system/storage")
