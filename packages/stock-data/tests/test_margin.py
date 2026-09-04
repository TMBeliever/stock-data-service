"""
测试融资融券 (Margin Trading) 接口
"""
import pytest
from unittest.mock import patch
import pandas as pd
from fastapi.testclient import TestClient
from service.app import app


client = TestClient(app)


class TestMarketMargin:
    """测试全市场两融走势接口"""

    @patch('akshare.stock_margin_sse')
    def test_market_margin_sh_success(self, mock_sse):
        """测试上交所全市场两融走势"""
        mock_df = pd.DataFrame([
            {
                '信用交易日期': '20260903',
                '融资余额': 1342763630194.0,
                '融资买入额': 77603882394.0,
                '融券余量': 3114846112.0,
                '融券余量金额': 18559843637.0,
                '融资融券余额': 1361323473831.0
            },
            {
                '信用交易日期': '20260902',
                '融资余额': 1345009259547.0,
                '融资买入额': 78383553522.0,
                '融券余量': 3148152437.0,
                '融券余量金额': 18834198146.0,
                '融资融券余额': 1363843457693.0
            }
        ])
        mock_sse.return_value = mock_df

        response = client.get("/api/v1/market/margin?market=SH&start=2026-09-01&end=2026-09-03")

        assert response.status_code == 200
        data = response.json()
        assert data['market'] == 'SH'
        assert data['count'] == 2
        assert len(data['data']) == 2

        first = data['data'][0]
        assert first['date'] == '2026-09-03'
        assert first['financing_balance'] == 1342763630194.0
        assert first['financing_buy'] == 77603882394.0
        assert first['securities_lending_volume'] == 3114846112.0
        assert first['securities_lending_balance'] == 18559843637.0
        assert first['total_balance'] == 1361323473831.0

    @patch('akshare.macro_china_market_margin_sz')
    def test_market_margin_sz_success(self, mock_sz):
        """测试深交所全市场两融走势"""
        mock_df = pd.DataFrame([
            {
                '日期': '2026-09-03',
                '融资买入额': 71012430000.0,
                '融资余额': 1276274000000.0,
                '融券卖出量': 0.28,
                '融券余量': None,
                '融券余额': 10618190000.0,
                '融资融券余额': 1286892000000.0
            }
        ])
        mock_sz.return_value = mock_df

        response = client.get("/api/v1/market/margin?market=SZ&start=2026-09-03&end=2026-09-03")

        assert response.status_code == 200
        data = response.json()
        assert data['market'] == 'SZ'
        assert data['count'] == 1

        first = data['data'][0]
        assert first['date'] == '2026-09-03'
        assert first['financing_balance'] == 1276274000000.0

    def test_market_margin_invalid_market(self):
        """测试无效市场标识"""
        response = client.get("/api/v1/market/margin?market=BJ")
        assert response.status_code == 422  # FastAPI enum validation

    def test_market_margin_invalid_market_string(self):
        """测试非法市场字符串"""
        response = client.get("/api/v1/market/margin?market=INVALID")
        assert response.status_code == 422


class TestStockMargin:
    """测试个股两融明细接口"""

    @patch('akshare.stock_margin_detail_sse')
    def test_stock_margin_sh_success(self, mock_detail):
        """测试上交所个股两融明细"""
        mock_df = pd.DataFrame([
            {
                '信用交易日期': '20260903',
                '标的证券代码': '600519',
                '标的证券简称': '贵州茅台',
                '融资余额': 17302398388.0,
                '融资买入额': 138924008.0,
                '融资偿还额': 50000000.0,
                '融券余量': 110419.0,
                '融券卖出量': 6700.0,
                '融券偿还量': 3000.0
            }
        ])
        mock_detail.return_value = mock_df

        response = client.get("/api/v1/stock/margin?symbol=600519&date=2026-09-03")

        assert response.status_code == 200
        data = response.json()
        assert data['symbol'] == '600519.SH.STK'
        assert data['found'] is True
        assert data['data']['financing_balance'] == 17302398388.0
        assert data['data']['lending_balance_volume'] == 110419.0

    @patch('akshare.stock_margin_detail_szse')
    def test_stock_margin_sz_success(self, mock_detail):
        """测试深交所个股两融明细"""
        mock_df = pd.DataFrame([
            {
                '证券代码': '000001',
                '证券简称': '平安银行',
                '融资买入额': 123556469.0,
                '融资余额': 4640385102.0,
                '融券卖出量': 386672.0,
                '融券余量': 7432137.0,
                '融券余额': 88293787.0,
                '融资融券余额': 4728678889.0
            }
        ])
        mock_detail.return_value = mock_df

        response = client.get("/api/v1/stock/margin?symbol=000001&date=2026-09-03")

        assert response.status_code == 200
        data = response.json()
        assert data['symbol'] == '000001.SZ.STK'
        assert data['found'] is True
        assert data['data']['financing_balance'] == 4640385102.0
        assert data['data']['total_balance'] == 4728678889.0

    @patch('akshare.stock_margin_detail_sse')
    def test_stock_margin_not_found(self, mock_detail):
        """测试非两融标的股票返回 found=False"""
        mock_df = pd.DataFrame([
            {
                '信用交易日期': '20260903',
                '标的证券代码': '510050',
                '标的证券简称': '50ETF',
                '融资余额': 1422686916.0,
                '融资买入额': 37299666.0,
                '融资偿还额': 39127540.0,
                '融券余量': 38225340.0,
                '融券卖出量': 2095700.0,
                '融券偿还量': 1486500.0
            }
        ])
        mock_detail.return_value = mock_df

        # 测试不存在的股票代码返回 found=False
        response = client.get("/api/v1/stock/margin?symbol=999999.SH&date=2026-09-03")

        assert response.status_code == 200
        data = response.json()
        assert data['found'] is False
        assert data['data'] is None

    def test_stock_margin_bj_rejected(self):
        """测试北交所标的明确拒绝 (北交所无两融业务)"""
        response = client.get("/api/v1/stock/margin?symbol=832000&date=2026-09-03")
        assert response.status_code == 400
        assert "北交所" in response.json()['detail']

    def test_stock_margin_us_rejected(self):
        """测试美股标的明确拒绝"""
        response = client.get("/api/v1/stock/margin?symbol=AAPL&date=2026-09-03")
        assert response.status_code == 400
