import pytest
from core.models import (
    AssetType, Market, KlinePeriod, AdjustType, 
    parse_symbol, format_symbol, SymbolInfo, KlinePoint, KlineResponse
)

def test_parse_symbol_standard():
    ticker, market, asset_type = parse_symbol("AAPL.US.STK")
    assert ticker == "AAPL"
    assert market == "US"
    assert asset_type == "STK"

    ticker, market, asset_type = parse_symbol("000300.SH.IDX")
    assert ticker == "000300"
    assert market == "SH"
    assert asset_type == "IDX"

    ticker, market, asset_type = parse_symbol("510300.SH.ETF")
    assert ticker == "510300"
    assert market == "SH"
    assert asset_type == "ETF"

def test_parse_symbol_inference():
    # 纯 6 位代码自动推断
    ticker, market, asset_type = parse_symbol("002594") # 比亚迪
    assert ticker == "002594"
    assert market == "SZ"
    assert asset_type == AssetType.STOCK.value

    ticker, market, asset_type = parse_symbol("600519") # 贵州茅台
    assert ticker == "600519"
    assert market == "SH"
    assert asset_type == AssetType.STOCK.value

    ticker, market, asset_type = parse_symbol("300750") # 宁德时代
    assert ticker == "300750"
    assert market == "SZ"
    assert asset_type == AssetType.STOCK.value

    ticker, market, asset_type = parse_symbol("510300") # 300ETF
    assert ticker == "510300"
    assert market == "SH"
    assert asset_type == AssetType.ETF.value

    ticker, market, asset_type = parse_symbol("159915") # 创业板ETF
    assert ticker == "159915"
    assert market == "SZ"
    assert asset_type == AssetType.ETF.value

    # 前缀写法推断
    ticker, market, asset_type = parse_symbol("sz002594")
    assert ticker == "002594"
    assert market == "SZ"
    assert asset_type == AssetType.STOCK.value

    # 自动推断指数
    ticker, market, asset_type = parse_symbol("000300.SH")
    assert ticker == "000300"
    assert market == "SH"
    assert asset_type == AssetType.INDEX.value

    # 自动推断 ETF
    ticker, market, asset_type = parse_symbol("510500.SH")
    assert ticker == "510500"
    assert market == "SH"
    assert asset_type == AssetType.ETF.value

    # 自动推断美股股票
    ticker, market, asset_type = parse_symbol("TSLA")
    assert ticker == "TSLA"
    assert market == "US"
    assert asset_type == AssetType.STOCK.value

def test_format_symbol():
    assert format_symbol("aapl", "us", "stk") == "AAPL.US.STK"
    assert format_symbol("600519", "sh", "stk") == "600519.SH.STK"

def test_kline_point_and_response():
    point = KlinePoint(
        timestamp=1704067200000,
        open=100.5,
        high=102.0,
        low=99.8,
        close=101.2,
        volume=10000.0,
        amount=1012000.0,
        factor=1.0,
        nav=None
    )
    assert point.timestamp == 1704067200000
    assert point.close == 101.2

    resp = KlineResponse(
        symbol="AAPL.US.STK",
        period="1d",
        adjust="raw",
        count=1,
        data=[point]
    )
    assert resp.count == 1
    assert resp.symbol == "AAPL.US.STK"
