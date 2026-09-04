"""
测试分析师一致预期端点
"""
import pytest
import pandas as pd
from unittest.mock import patch
from fastapi.testclient import TestClient
from service.app import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.asyncio
async def test_analyst_consensus(client):
    """测试分析师一致预期端点"""
    # 构造真实的 DataFrame
    mock_df = pd.DataFrame([
        {
            '代码': '600519',
            '名称': '贵州茅台',
            '研报数': 45,
            '机构投资评级(近六个月)-买入': 36,
            '机构投资评级(近六个月)-增持': 9,
            '机构投资评级(近六个月)-中性': 0,
            '机构投资评级(近六个月)-减持': 0,
            '机构投资评级(近六个月)-卖出': 0,
            '2025预测每股收益': 65.85,
            '2026预测每股收益': 67.66,
            '2027预测每股收益': 71.52,
            '2028预测每股收益': 75.21
        }
    ])

    import akshare as ak
    with patch.object(ak, 'stock_profit_forecast_em', return_value=mock_df):
        from service.routes.analyst import get_analyst_consensus
        result = await get_analyst_consensus(symbol='600519', market='SH')

    assert result.symbol == '600519.SH.STK'
    assert result.data_source == '东方财富 (East Money)'
    assert result.report_count == 45
    assert result.rating_buy == 36
    assert result.rating_accumulate == 9
    assert result.rating_neutral == 0
    assert result.rating_reduce == 0
    assert result.rating_sell == 0

    assert len(result.eps_forecasts) == 4
    assert result.eps_forecasts[0].year == 2025
    assert result.eps_forecasts[0].eps == 65.85
    assert result.eps_forecasts[1].year == 2026
    assert result.eps_forecasts[1].eps == 67.66


@pytest.mark.asyncio
async def test_analyst_consensus_not_found(client):
    """测试找不到分析师预期数据"""
    # 构造空 DataFrame
    mock_df = pd.DataFrame([
        {'代码': '000001', '名称': '平安银行', '研报数': 10}
    ])

    import akshare as ak
    with patch.object(ak, 'stock_profit_forecast_em', return_value=mock_df):
        from service.routes.analyst import get_analyst_consensus
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await get_analyst_consensus(symbol='999999', market='SH')

        assert exc_info.value.status_code == 404
        assert 'No analyst consensus' in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_analyst_consensus_invalid_market(client):
    """测试无效市场参数"""
    from service.routes.analyst import get_analyst_consensus
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await get_analyst_consensus(symbol='AAPL', market='US')

    assert exc_info.value.status_code == 400
    assert 'only available for A-share' in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_analyst_consensus_with_none_values(client):
    """测试包含 None 值的数据"""
    # 构造包含 NaN 的 DataFrame
    mock_df = pd.DataFrame([
        {
            '代码': '000001',
            '名称': '平安银行',
            '研报数': None,
            '机构投资评级(近六个月)-买入': 10,
            '机构投资评级(近六个月)-增持': 5,
            '机构投资评级(近六个月)-中性': 2,
            '机构投资评级(近六个月)-减持': 0,
            '机构投资评级(近六个月)-卖出': 0,
            '2025预测每股收益': None,
            '2026预测每股收益': 1.5,
            '2027预测每股收益': None,
            '2028预测每股收益': None
        }
    ])

    import akshare as ak
    with patch.object(ak, 'stock_profit_forecast_em', return_value=mock_df):
        from service.routes.analyst import get_analyst_consensus
        result = await get_analyst_consensus(symbol='000001', market='SZ')

    assert result.symbol == '000001.SZ.STK'
    assert result.report_count == 0  # None 转为 0
    assert result.rating_buy == 10
    assert result.rating_accumulate == 5
    assert result.rating_neutral == 2

    # 只返回非 None 的 EPS 预测
    assert len(result.eps_forecasts) == 1
    assert result.eps_forecasts[0].year == 2026
    assert result.eps_forecasts[0].eps == 1.5
