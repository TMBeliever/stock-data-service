from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field

class AssetType(str, Enum):
    STOCK = "STK"
    INDEX = "IDX"
    ETF = "ETF"
    FX = "FX"
    CRYPTO = "CRYPTO"

class Market(str, Enum):
    SH = "SH"      # 上海证券交易所
    SZ = "SZ"      # 深圳证券交易所
    BJ = "BJ"      # 北京证券交易所
    US = "US"      # 美国市场 (NYSE, NASDAQ, AMEX)
    HK = "HK"      # 香港交易所
    BINANCE = "BINANCE"
    FX = "FX"

class KlinePeriod(str, Enum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    M60 = "60m"
    D1 = "1d"
    W1 = "1w"
    MON1 = "1M"
    Y1 = "1Y"

class AdjustType(str, Enum):
    RAW = "raw"    # 不复权 (原始价格)
    QFQ = "qfq"    # 前复权 (Forward Adjusted)
    HFQ = "hfq"    # 后复权 (Backward Adjusted)

class SymbolInfo(BaseModel):
    symbol: str = Field(..., description="规范化代码: [TICKER].[MARKET].[TYPE], 如 600519.SH.STK, SPY.US.ETF")
    ticker: str = Field(..., description="原始Ticker代码, 如 600519, SPY")
    market: Market
    asset_type: AssetType
    name: str = Field(..., description="标的名称")
    currency: str = Field(default="CNY", description="交易计价货币: USD, CNY, HKD")
    is_benchmark: bool = Field(default=False, description="是否核心基准资产(主动更新与常驻)")
    is_active: bool = Field(default=True, description="是否处于上市交易状态")
    extra_info: Optional[str] = Field(default=None, description="JSON扩展信息(如ETF关联指数)")

class KlinePoint(BaseModel):
    timestamp: int = Field(..., description="UTC 毫秒时间戳")
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: Optional[float] = 0.0
    factor: Optional[float] = None      # 复权因子 (无复权或缺失时为 None，不静默伪造为 1.0)
    nav: Optional[float] = None         # ETF 单位净值 (如适用)
    # 可选技术分析指标字段
    ma5: Optional[float] = None
    ma10: Optional[float] = None
    ma20: Optional[float] = None
    ma60: Optional[float] = None
    macd_dif: Optional[float] = None
    macd_dea: Optional[float] = None
    macd_hist: Optional[float] = None
    rsi: Optional[float] = None
    boll_upper: Optional[float] = None
    boll_mid: Optional[float] = None
    boll_lower: Optional[float] = None
    atr: Optional[float] = None

class KlineResponse(BaseModel):
    symbol: str
    period: str
    adjust: str
    count: int
    latest: Optional[KlinePoint] = None
    data: List[KlinePoint]

NAME_TO_SYMBOL_MAP = {
    "招商": ("600036", "SH", "STK"),
    "招商银行": ("600036", "SH", "STK"),
    "招行": ("600036", "SH", "STK"),
    "贵州茅台": ("600519", "SH", "STK"),
    "茅台": ("600519", "SH", "STK"),
    "比亚迪": ("002594", "SZ", "STK"),
    "宁德时代": ("300750", "SZ", "STK"),
    "平安银行": ("000001", "SZ", "STK"),
    "中国平安": ("601318", "SH", "STK"),
    "五粮液": ("000858", "SZ", "STK"),
    "长江电力": ("600900", "SH", "STK"),
    "紫金矿业": ("601899", "SH", "STK"),
    "中信证券": ("600030", "SH", "STK"),
    "腾讯": ("00700", "HK", "STK"),
    "腾讯控股": ("00700", "HK", "STK"),
    "阿里巴巴": ("09988", "HK", "STK"),
    "美团": ("03690", "HK", "STK"),
    "沪深300": ("000300", "SH", "IDX"),
    "中证500": ("000905", "SH", "IDX"),
    "中证1000": ("000852", "SH", "IDX"),
    "上证指数": ("000001", "SH", "IDX"),
    "上证50": ("000016", "SH", "IDX"),
    "创业板指": ("399006", "SZ", "IDX"),
    "深证成指": ("399001", "SZ", "IDX"),
    "恒生指数": ("HSI", "HK", "IDX"),
    "纳斯达克": ("NDX", "US", "IDX"),
    "标普500": ("SPX", "US", "IDX"),
    "道琼斯": ("DJI", "US", "IDX"),
}

def parse_symbol(symbol_str: str) -> tuple[str, str, str]:
    """
    智能解析标的代码。
    全面支持：
      1. 标准三段式: AAPL.US.STK, 002594.SZ.STK
      2. 市场后缀简写: 002594.SZ, 600519.SH, AAPL.US, 00700.HK
      3. 交易所前缀简写: sz002594, sh600519
      4. 常用股票/指数中文名称智能解析与大模型兜底翻译
      5. 纯代码全自动推断
    """
    clean_sym = symbol_str.strip()

    # 1. 尝试多级智能解析 (内存字典 -> 本地 SQLite 缓存 -> 大模型语义翻译)
    from core.symbol_resolver import resolve_symbol_smart
    smart_res = resolve_symbol_smart(clean_sym)
    if smart_res:
        return smart_res

    raw = clean_sym.upper()

    # 处理形如 SH600519 / SZ002594 前缀格式
    if (raw.startswith("SH") or raw.startswith("SZ") or raw.startswith("BJ")) and len(raw) == 8 and raw[2:].isdigit():
        market = raw[:2]
        ticker = raw[2:]
        return parse_symbol(f"{ticker}.{market}")

    parts = raw.split(".")
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    elif len(parts) == 2:
        ticker, market = parts[0], parts[1]
        # 常见指数
        if ticker in ["000300", "000905", "399001", "399006", "SPX", "NDX", "DJI", "HSI"]:
            return ticker, market, AssetType.INDEX.value
        elif ticker.startswith("51") or ticker.startswith("56") or ticker.startswith("58") or ticker.startswith("15") or ticker.startswith("16") or ticker in ["SPY", "QQQ", "IVV", "VTI", "GLD"]:
            return ticker, market, AssetType.ETF.value
        else:
            return ticker, market, AssetType.STOCK.value
    else:
        # 纯代码智能推断 (无小数点)
        code = parts[0]
        
        # 1. 纯数字
        if code.isdigit():
            # 6位数字 -> A股
            if len(code) == 6:
                if code in ["000300", "000905", "000001"] and code != "000001":
                    return code, Market.SH.value, AssetType.INDEX.value
                elif code.startswith("399"):
                    return code, Market.SZ.value, AssetType.INDEX.value
                elif code.startswith("51") or code.startswith("56") or code.startswith("58"):
                    return code, Market.SH.value, AssetType.ETF.value
                elif code.startswith("15") or code.startswith("16"):
                    return code, Market.SZ.value, AssetType.ETF.value
                elif code.startswith("60") or code.startswith("68"):
                    return code, Market.SH.value, AssetType.STOCK.value
                elif code.startswith("00") or code.startswith("30"):
                    # 002594 比亚迪, 000001 平安银行, 300750 宁德时代
                    return code, Market.SZ.value, AssetType.STOCK.value
                elif code.startswith("8") or code.startswith("4") or code.startswith("9"):
                    return code, Market.BJ.value, AssetType.STOCK.value
                else:
                    return code, Market.SH.value, AssetType.STOCK.value
            # 5位数字 -> 港股 (如 00700 腾讯控股, 09988 阿里巴巴)
            elif len(code) == 5:
                return code, Market.HK.value, AssetType.STOCK.value
            # 4位数字 -> 补齐5位港股 (如 700 -> 00700)
            elif len(code) <= 4:
                return code.zfill(5), Market.HK.value, AssetType.STOCK.value

        # 2. 纯字母 -> 美股/指数/ETF
        if code in ["SPY", "QQQ", "IVV", "VOO", "VTI", "GLD", "TLT"]:
            return code, Market.US.value, AssetType.ETF.value
        elif code in ["SPX", "NDX", "DJI", "VIX"]:
            return code, Market.US.value, AssetType.INDEX.value
        elif code == "HSI":
            return code, Market.HK.value, AssetType.INDEX.value
        else:
            return code, Market.US.value, AssetType.STOCK.value

def format_symbol(ticker: str, market: str, asset_type: str) -> str:
    return f"{ticker.upper()}.{market.upper()}.{asset_type.upper()}"

class SnapshotItem(BaseModel):
    symbol: str = Field(..., description="规范化标的代码: [TICKER].[MARKET].[TYPE]")
    ticker: Optional[str] = Field(None, description="标的代码/简码 (如 600519, AAPL)")
    name: str = Field(..., description="标的名称")
    latest_price: Optional[float] = Field(None, description="最新成交价格 (无实时成交时为 None)")
    pre_close: Optional[float] = Field(None, description="昨收价")
    open: Optional[float] = Field(None, description="今开盘价")
    high: Optional[float] = Field(None, description="今日最高价")
    low: Optional[float] = Field(None, description="今日最低价")
    change: Optional[float] = Field(None, description="涨跌额")
    pct_change: Optional[float] = Field(None, description="涨跌幅(%)")
    volume: Optional[float] = Field(None, description="今日成交量")
    amount: Optional[float] = Field(None, description="今日成交额")
    turnover_rate: Optional[float] = Field(None, description="换手率(%)")
    pe: Optional[float] = Field(None, description="市盈率(动态/TTM)")
    pe_ttm: Optional[float] = Field(None, description="市盈率(TTM)")
    pb: Optional[float] = Field(None, description="市净率")
    total_market_cap: Optional[float] = Field(None, description="总市值 (亿元/亿美元/亿港元)")
    market_cap: Optional[float] = Field(None, description="总市值 (亿元/亿美元/亿港元)")
    circulating_market_cap: Optional[float] = Field(None, description="流通市值 (亿元/亿美元/亿港元)")
    float_market_cap: Optional[float] = Field(None, description="流通市值 (亿元/亿美元/亿港元)")
    dividend_yield: Optional[float] = Field(None, description="股息率(%)")
    dividend_yield_pct: Optional[float] = Field(None, description="股息率(%)")
    nav: Optional[float] = Field(None, description="ETF 实时单位净值/IOPV (仅 ETF 标的有效)")
    premium_rate: Optional[float] = Field(None, description="ETF 折溢价率(%) = (最新价 - NAV) / NAV * 100")
    ask_prices: Optional[List[float]] = Field(None, description="卖一至卖五档挂单价格 (仅 A股支持，其他市场为 None)")
    ask_volumes: Optional[List[float]] = Field(None, description="卖一至卖五档挂单量 (手)")
    bid_prices: Optional[List[float]] = Field(None, description="买一至买五档挂单价格 (仅 A股支持，其他市场为 None)")
    bid_volumes: Optional[List[float]] = Field(None, description="买一至买五档挂单量 (手)")
    timestamp: Optional[int] = Field(None, description="行情时间戳 (UTC 毫秒)")

class SnapshotBatchRequest(BaseModel):
    symbols: List[str] = Field(..., description="批量股票代码列表，如 ['600519.SH.STK', 'AAPL.US.STK']")

class SnapshotBatchResponse(BaseModel):
    count: int = Field(..., description="获取到的有效实时快照数量")
    data: List[SnapshotItem] = Field(default_factory=list, description="有效行情快照列表")
    missing: List[str] = Field(default_factory=list, description="无实时行情或代码未识别的标的列表 (严格拒绝虚构数据)")

