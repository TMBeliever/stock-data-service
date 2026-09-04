import polars as pl
from unittest.mock import patch, MagicMock
from quant_core.client.data_client import DataClient

def test_data_client_bars_conversion():
    client = DataClient()
    mock_df = pl.DataFrame({
        "timestamp": [1600000000000, 1600086400000],
        "open": [10.0, 11.0],
        "high": [12.0, 12.5],
        "low": [9.5, 10.8],
        "close": [11.0, 12.0],
        "volume": [1000.0, 2000.0],
        "amount": [11000.0, 24000.0]
    })
    
    with patch.object(client, "get_kline_df", return_value=mock_df):
        bars = client.get_bars("600519.SH.STK")
        assert len(bars) == 2
        assert bars[0].symbol == "600519.SH.STK"
        assert bars[0].close == 11.0
        assert bars[1].close == 12.0

def test_data_client_snapshots():
    client = DataClient()
    with patch("httpx.Client.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{
                "symbol": "600519.SH.STK",
                "timestamp": 1600000000000,
                "price": 1800.0,
                "open": 1790.0,
                "high": 1810.0,
                "low": 1780.0,
                "prev_close": 1785.0,
                "volume": 10000.0,
                "turnover": 18000000.0
            }]
        }
        mock_post.return_value = mock_resp
        res = client.get_snapshots(["600519.SH.STK"])
        assert "600519.SH.STK" in res
        assert res["600519.SH.STK"].price == 1800.0
