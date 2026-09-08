import pytest
from unittest.mock import MagicMock, patch
import httpx
import polars as pl
from quant_core.client.hub_client import DataHubClient

def test_hub_client_search_apis():
    client = DataHubClient()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "items": [{"provider": "akshare", "api_name": "stock_hk_valuation_baidu"}]
    }
    mock_resp.raise_for_status.return_value = None

    with patch.object(client._http, "get", return_value=mock_resp) as mock_get:
        items = client.search_apis(q="valuation", provider="akshare")
        assert len(items) == 1
        assert items[0]["api_name"] == "stock_hk_valuation_baidu"
        mock_get.assert_called_once()


def test_hub_client_invoke_bypass_cache():
    client = DataHubClient()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "status": "success",
        "provider": "akshare",
        "api_name": "stock_hk_valuation_baidu",
        "from_cache": False,
        "bypassed_cache": True,
        "data": [{"date": "2026-09-08", "value": 25.5}]
    }
    mock_resp.raise_for_status.return_value = None

    with patch.object(client._http, "post", return_value=mock_resp) as mock_post:
        df = client.akshare.stock_hk_valuation_baidu(
            symbol="00700",
            bypass_cache=True
        )
        assert isinstance(df, pl.DataFrame)
        assert len(df) == 1
        assert "date" in df.columns
        assert df["value"][0] == 25.5
        mock_post.assert_called_once()
