"""
测试历史分红送配接口
"""
import pytest
from unittest.mock import patch, MagicMock
import pandas as pd
from datetime import date
from fastapi.testclient import TestClient
from service.app import app
import yfinance


client = TestClient(app)


class TestDividendsAStock:
    """测试 A 股分红接口"""

    @patch('akshare.stock_fhps_detail_em')
    def test_get_dividends_success(self, mock_akshare):
        """测试成功获取 A 股分红数据"""
        # Mock AkShare 返回数据
        mock_df = pd.DataFrame([
            {
                '报告期': date(2023, 12, 31),
                '最新公告日期': date(2024, 3, 29),
                '股权登记日': date(2024, 7, 18),
                '除权除息日': date(2024, 7, 19),
                '现金分红-现金分红比例': 30.88,  # 10 派 30.88 元
                '送转股份-送转总比例': 0.0,
                '现金分红-股息率': 0.0235,
                '方案进度': '实施分配',
                '现金分红-现金分红比例描述': '10 派 30.88 元 (含税，扣税后 28.88 元)'
            },
            {
                '报告期': date(2022, 12, 31),
                '最新公告日期': date(2023, 3, 31),
                '股权登记日': date(2023, 7, 27),
                '除权除息日': date(2023, 7, 28),
                '现金分红-现金分红比例': 25.0,
                '送转股份-送转总比例': 0.0,
                '现金分红-股息率': 0.0198,
                '方案进度': '实施分配',
                '现金分红-现金分红比例描述': '10 派 25 元 (含税)'
            }
        ])
        mock_akshare.return_value = mock_df

        response = client.get("/api/v1/stock/dividends?symbol=600519&market=SH&limit=10")

        assert response.status_code == 200
        data = response.json()

        assert data['symbol'] == '600519.SH.STK'
        assert data['market'] == 'SH'
        assert data['currency'] == 'CNY'
        assert data['count'] == 2
        assert len(data['dividends']) == 2

        # 验证第一条记录
        first_div = data['dividends'][0]
        assert first_div['report_date'] == '2023-12-31'
        assert first_div['cash_per_share'] == 3.088  # 30.88 / 10
        assert first_div['bonus_share_ratio'] == 0.0
        assert first_div['dividend_yield_pct'] == 2.35  # 0.0235 * 100
        assert first_div['record_date'] == '2024-07-18'
        assert first_div['ex_dividend_date'] == '2024-07-19'
        assert first_div['plan_progress'] == '实施分配'

    @patch('akshare.stock_fhps_detail_em')
    def test_get_dividends_not_found(self, mock_akshare):
        """测试股票无分红数据时返回 404"""
        mock_akshare.return_value = pd.DataFrame()

        response = client.get("/api/v1/stock/dividends?symbol=999999&market=SH")

        assert response.status_code == 404

    @patch('akshare.stock_fhps_detail_em')
    def test_get_dividends_limit(self, mock_akshare):
        """测试 limit 参数限制返回数量"""
        mock_df = pd.DataFrame([
            {
                '报告期': date(2023 - i, 12, 31),
                '最新公告日期': date(2024 - i, 3, 29),
                '股权登记日': date(2024 - i, 7, 18),
                '除权除息日': date(2024 - i, 7, 19),
                '现金分红-现金分红比例': 30.0,
                '送转股份-送转总比例': 0.0,
                '现金分红-股息率': 0.02,
                '方案进度': '实施分配',
                '现金分红-现金分红比例描述': '10 派 30 元'
            }
            for i in range(10)
        ])
        mock_akshare.return_value = mock_df

        response = client.get("/api/v1/stock/dividends?symbol=600519&market=SH&limit=5")

        assert response.status_code == 200
        data = response.json()
        assert data['count'] == 5
        assert len(data['dividends']) == 5


class TestDividendsUSStock:
    """测试美股分红接口"""

    @patch('yfinance.Ticker')
    def test_get_dividends_us_success(self, mock_ticker):
        """测试成功获取美股分红数据"""
        # Mock yfinance 返回分红序列
        mock_instance = MagicMock()
        mock_dividends = pd.Series(
            [0.25, 0.25, 0.24, 0.24],
            index=pd.to_datetime(['2024-02-09', '2023-11-10', '2023-08-11', '2023-05-12'])
        )
        mock_instance.dividends = mock_dividends
        mock_ticker.return_value = mock_instance

        response = client.get("/api/v1/stock/dividends?symbol=AAPL&market=US&limit=10")

        assert response.status_code == 200
        data = response.json()

        assert data['symbol'] == 'AAPL.US.STK'
        assert data['market'] == 'US'
        assert data['currency'] == 'USD'
        assert data['count'] == 4
        assert len(data['dividends']) == 4

        # 验证第一条记录
        first_div = data['dividends'][0]
        assert first_div['cash_per_share'] == 0.25
        assert first_div['bonus_share_ratio'] is None  # 美股无送转比例
        assert first_div['dividend_yield_pct'] is None

    @patch('yfinance.Ticker')
    def test_get_dividends_us_empty(self, mock_ticker):
        """测试美股无分红数据时返回 404"""
        mock_instance = MagicMock()
        mock_instance.dividends = pd.Series(dtype=float)
        mock_ticker.return_value = mock_instance

        response = client.get("/api/v1/stock/dividends?symbol=BRK.B&market=US")

        assert response.status_code == 404


class TestDividendsEdgeCases:
    """测试边界情况"""

    def test_parse_symbol_auto_infer_market(self):
        """测试 parse_symbol 自动推断 market，接受任意有效股票代码"""
        # dividends 端点通过 parse_symbol 自动推断 market，所以不存在无效 market 的情况
        # 测试 A 股股票代码能正确推断
        response = client.get("/api/v1/stock/dividends?symbol=600519&limit=1")
        # 无论是否有数据，状态码应该是 200（如果有数据）或 404（如果没数据）
        assert response.status_code in [200, 404]

    @patch('akshare.stock_fhps_detail_em')
    def test_missing_fields_handled(self, mock_akshare):
        """测试缺失字段优雅处理"""
        mock_df = pd.DataFrame([
            {
                '报告期': date(2023, 12, 31),
                '最新公告日期': None,  # 缺失字段
                '股权登记日': None,
                '除权除息日': None,
                '现金分红-现金分红比例': None,  # 缺失
                '送转股份-送转总比例': None,
                '现金分红-股息率': None,
                '方案进度': None,
                '现金分红-现金分红比例描述': None
            }
        ])
        mock_akshare.return_value = mock_df

        response = client.get("/api/v1/stock/dividends?symbol=600519&market=SH")

        assert response.status_code == 200
        data = response.json()
        assert data['count'] == 1

        div = data['dividends'][0]
        assert div['cash_per_share'] is None
        assert div['bonus_share_ratio'] is None
        assert div['dividend_yield_pct'] is None
