"""
测试宏观经济数据端点 (PMI/CPI/PPI/M2)
使用真实 pandas DataFrame 作为 mock 数据，避免 MagicMock 与 DataFrame API 不匹配的问题。
"""
import pytest
import pandas as pd
from unittest.mock import patch
from fastapi.testclient import TestClient
from service.app import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def pmi_df():
    """构造 PMI 测试 DataFrame"""
    return pd.DataFrame([
        {
            '月份': '2026年08月份',
            '制造业-指数': 49.8,
            '制造业-同比增长': 0.81,
            '非制造业-指数': 49.0,
            '非制造业-同比增长': -2.58
        },
        {
            '月份': '2026年07月份',
            '制造业-指数': 49.2,
            '制造业-同比增长': -0.20,
            '非制造业-指数': 49.0,
            '非制造业-同比增长': -2.19
        },
        {
            '月份': '2026年06月份',
            '制造业-指数': 50.3,
            '制造业-同比增长': 1.21,
            '非制造业-指数': 50.2,
            '非制造业-同比增长': -0.59
        }
    ])


@pytest.fixture
def cpi_df():
    """构造 CPI 测试 DataFrame"""
    return pd.DataFrame([
        {
            '月份': '2026年07月份',
            '全国-当月': 100.5,
            '全国-同比增长': 0.5,
            '全国-环比增长': -0.1,
            '全国-累计': 100.9,
            '城市-当月': 100.5,
            '城市-同比增长': 0.5,
            '城市-环比增长': -0.1,
            '城市-累计': 101.0,
            '农村-当月': 100.4,
            '农村-同比增长': 0.4,
            '农村-环比增长': -0.2,
            '农村-累计': 100.7
        },
        {
            '月份': '2026年06月份',
            '全国-当月': 101.0,
            '全国-同比增长': 1.0,
            '全国-环比增长': -0.3,
            '全国-累计': 101.0,
            '城市-当月': 101.0,
            '城市-同比增长': 1.0,
            '城市-环比增长': -0.4,
            '城市-累计': 101.0,
            '农村-当月': 100.8,
            '农村-同比增长': 0.8,
            '农村-环比增长': 0.0,
            '农村-累计': 100.8
        }
    ])


@pytest.fixture
def ppi_df():
    """构造 PPI 测试 DataFrame"""
    return pd.DataFrame([
        {'月份': '2026年07月份', '当月': 103.5, '当月同比增长': 3.5, '累计': 101.8},
        {'月份': '2026年06月份', '当月': 104.1, '当月同比增长': 4.1, '累计': 101.5}
    ])


@pytest.fixture
def m2_df():
    """构造 M2 测试 DataFrame (按日期倒序)"""
    return pd.DataFrame([
        {'商品': '中国M2货币供应年率报告', '日期': '2026-08-15', '今值': 7.3, '预测值': 7.2, '前值': 7.1},
        {'商品': '中国M2货币供应年率报告', '日期': '2026-07-15', '今值': 7.2, '预测值': 7.1, '前值': 7.0},
        {'商品': '中国M2货币供应年率报告', '日期': '2026-06-15', '今值': 7.0, '预测值': 7.0, '前值': 6.9}
    ])


@pytest.mark.asyncio
async def test_macro_pmi(client, pmi_df):
    """测试宏观经济数据端点 - PMI"""
    import akshare as ak
    with patch.object(ak, 'macro_china_pmi', return_value=pmi_df):
        from service.routes.advanced import get_china_pmi
        result = await get_china_pmi(limit=3)

    assert result.count == 3
    assert result.data[0].month == '2026-08'
    assert result.data[0].manufacturing_index == 49.8
    assert result.data[0].manufacturing_yoy_pct == 0.81
    assert result.data[0].non_manufacturing_index == 49.0
    assert result.data[0].non_manufacturing_yoy_pct == -2.58
    assert result.data[1].month == '2026-07'
    assert result.data[2].month == '2026-06'


@pytest.mark.asyncio
async def test_macro_cpi(client, cpi_df):
    """测试宏观经济数据端点 - CPI"""
    import akshare as ak
    with patch.object(ak, 'macro_china_cpi', return_value=cpi_df):
        from service.routes.advanced import get_china_cpi
        result = await get_china_cpi(limit=2)

    assert result.count == 2
    assert result.data[0].month == '2026-07'
    assert result.data[0].national_yoy_pct == 0.5
    assert result.data[0].national_mom_pct == -0.1
    assert result.data[0].city_yoy_pct == 0.5
    assert result.data[0].rural_yoy_pct == 0.4


@pytest.mark.asyncio
async def test_macro_ppi(client, ppi_df):
    """测试宏观经济数据端点 - PPI"""
    import akshare as ak
    with patch.object(ak, 'macro_china_ppi', return_value=ppi_df):
        from service.routes.advanced import get_china_ppi
        result = await get_china_ppi(limit=2)

    assert result.count == 2
    assert result.data[0].month == '2026-07'
    assert result.data[0].current_value == 103.5
    assert result.data[0].yoy_pct == 3.5


@pytest.mark.asyncio
async def test_macro_m2(client, m2_df):
    """测试宏观经济数据端点 - M2"""
    import akshare as ak
    with patch.object(ak, 'macro_china_m2_yearly', return_value=m2_df):
        from service.routes.advanced import get_china_m2
        result = await get_china_m2(limit=3)

    assert result.count == 3
    assert result.data[0].date == '2026-08-15'
    assert result.data[0].m2_yoy_pct == 7.3


@pytest.mark.asyncio
async def test_macro_empty_response(client):
    """测试空数据响应 - 应返回 503 错误"""
    import akshare as ak
    import pandas as pd
    from fastapi import HTTPException
    from unittest.mock import patch

    empty_df = pd.DataFrame()

    with patch.object(ak, 'macro_china_pmi', return_value=empty_df):
        from service.routes.advanced import get_china_pmi

        try:
            await get_china_pmi(limit=3)
            assert False, "Expected HTTPException"
        except HTTPException as e:
            assert e.status_code == 503
            assert "PMI data currently unavailable" in str(e.detail)
