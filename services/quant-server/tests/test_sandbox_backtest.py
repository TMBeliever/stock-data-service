import pytest
from fastapi.testclient import TestClient

from quant_server.main import app
from quant_server.api.sandbox import StrategyCodeSandbox, SecurityCheckError

client = TestClient(app)

VALID_MA_CODE = """
from quant_core.core.base_strategy import BaseStrategy
from quant_core.core.models import Bar

class TestMAStrategy(BaseStrategy):
    def __init__(self):
        super().__init__(name="TestMA")
        self.fast = 5
        self.slow = 10

    def on_bar(self, bar: Bar):
        closes = self.context.get_closes(bar.symbol, n=self.slow + 2)
        if len(closes) < self.slow + 1:
            return
        ma_fast = sum(closes[-self.fast:]) / self.fast
        ma_slow = sum(closes[-self.slow:]) / self.slow
        pos = self.get_position(bar.symbol)
        if ma_fast > ma_slow and pos.quantity == 0:
            self.order_target_percent(bar.symbol, 0.8, reason="Golden Cross")
        elif ma_fast < ma_slow and pos.available_quantity > 0:
            self.close_position(bar.symbol, reason="Death Cross")
"""

MALICIOUS_OS_CODE = """
import os
from quant_core.core.base_strategy import BaseStrategy

class HackStrategy(BaseStrategy):
    def on_bar(self, bar):
        os.system("rm -rf /")
"""

MALICIOUS_EVAL_CODE = """
from quant_core.core.base_strategy import BaseStrategy

class EvalStrategy(BaseStrategy):
    def on_bar(self, bar):
        eval("1+1")
"""

MALICIOUS_ATTR_CODE = """
from quant_core.core.base_strategy import BaseStrategy

class SubclassExploit(BaseStrategy):
    def on_bar(self, bar):
        x = ().__class__.__bases__[0].__subclasses__()
"""

SYNTAX_ERROR_CODE = """
class Broken(BaseStrategy
    def on_bar(self, bar):
        pass
"""

NO_STRATEGY_CLASS_CODE = """
def calculate():
    return 42
"""

def test_sandbox_ast_validation_success():
    cls = StrategyCodeSandbox.load_strategy_class(VALID_MA_CODE)
    assert cls.__name__ == "TestMAStrategy"

def test_sandbox_catches_malicious_os():
    with pytest.raises(SecurityCheckError) as exc_info:
        StrategyCodeSandbox.load_strategy_class(MALICIOUS_OS_CODE)
    assert "禁止导入模块 'os'" in str(exc_info.value)

def test_sandbox_catches_eval():
    with pytest.raises(SecurityCheckError) as exc_info:
        StrategyCodeSandbox.load_strategy_class(MALICIOUS_EVAL_CODE)
    assert "禁止调用高危函数 'eval()'" in str(exc_info.value)

def test_sandbox_catches_subclasses_attr():
    with pytest.raises(SecurityCheckError) as exc_info:
        StrategyCodeSandbox.load_strategy_class(MALICIOUS_ATTR_CODE)
    assert "禁止访问底层反射属性" in str(exc_info.value)

def test_sandbox_catches_syntax_error():
    with pytest.raises(ValueError) as exc_info:
        StrategyCodeSandbox.load_strategy_class(SYNTAX_ERROR_CODE)
    assert "Python 语法错误" in str(exc_info.value)

def test_sandbox_catches_no_strategy():
    with pytest.raises(ValueError) as exc_info:
        StrategyCodeSandbox.load_strategy_class(NO_STRATEGY_CLASS_CODE)
    assert "未在代码中找到继承自 BaseStrategy" in str(exc_info.value)

def test_endpoint_run_custom_backtest_success():
    payload = {
        "symbol": "510300.SH.ETF",
        "code": VALID_MA_CODE,
        "start": "2024-01-01",
        "end": "2024-03-01",
        "initial_cash": 100000.0
    }
    response = client.post("/api/v1/backtest/run-custom", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    assert "summary" in data
    assert "daily_records" in data
    assert "benchmark_records" in data
    assert "trades" in data
    assert data["summary"]["initial_cash"] == 100000.0

def test_endpoint_run_custom_security_block():
    payload = {
        "symbol": "510300.SH.ETF",
        "code": MALICIOUS_OS_CODE,
        "start": "2024-01-01",
        "initial_cash": 100000.0
    }
    response = client.post("/api/v1/backtest/run-custom", json=payload)
    assert response.status_code == 400
    assert "安全策略拦截" in response.json()["detail"]

def test_endpoint_sandbox_validate_valid():
    response = client.post("/api/v1/sandbox/validate", json={"code": VALID_MA_CODE})
    assert response.status_code == 200
    data = response.json()
    assert data["is_valid"] is True
    assert data["strategy_name"] == "TestMA"

def test_endpoint_sandbox_validate_invalid_syntax():
    response = client.post("/api/v1/sandbox/validate", json={"code": SYNTAX_ERROR_CODE})
    assert response.status_code == 200
    data = response.json()
    assert data["is_valid"] is False
    assert "语法错误" in data["error"]

def test_quant_core_2_api_backtest():
    code = """
from quant_core.core.base_strategy import BaseStrategy
from quant_core.core.models import Bar

class StreamStrategy(BaseStrategy):
    def on_bar(self, bar: Bar):
        ma5 = self.sma(5)
        ma10 = self.sma(10)
        if self.cross_over(5, 10) and not self.position:
            self.order_target_percent(0.8, reason="金叉开仓")
        elif self.cross_under(5, 10) and self.position:
            self.close_position(reason="死叉平仓")
"""
    payload = {
        "symbol": "510300.SH.ETF",
        "code": code,
        "start": "2024-01-01",
        "end": "2024-03-01",
        "initial_cash": 100000.0
    }
    response = client.post("/api/v1/backtest/run-custom", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["summary"]["initial_cash"] == 100000.0
    assert len(data["daily_records"]) > 0


def test_custom_backtest_multi_symbols():
    code = """
from quant_core.core.base_strategy import BaseStrategy
from quant_core.core.models import Bar

class MultiSymbolTestStrategy(BaseStrategy):
    def on_bar(self, bar: Bar):
        # 针对不同标的进行等权重调仓
        pos = self.positions.get(bar.symbol)
        if not pos or pos.quantity == 0:
            self.order_target_percent(bar.symbol, 0.45, reason=f"分配标的{bar.symbol}")
"""
    payload = {
        "symbols": ["510300.SH.ETF", "510880.SH.ETF"],
        "benchmark": "510300.SH.ETF",
        "code": code,
        "start": "2024-01-01",
        "end": "2024-03-01",
        "initial_cash": 200000.0
    }
    response = client.post("/api/v1/backtest/run-custom", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["summary"]["initial_cash"] == 200000.0
    assert len(data["daily_records"]) > 0
    assert "symbols" in data
    assert "510300.SH.ETF" in data["symbols"]
    assert "510880.SH.ETF" in data["symbols"]
    assert data["benchmark_symbol"] == "510300.SH.ETF"
    assert len(data["benchmark_records"]) > 0


