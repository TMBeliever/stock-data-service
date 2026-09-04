import pytest
from cli import init_system, show_disk
from core.database import meta_db
from storage.sentinel import sentinel

@pytest.mark.asyncio
async def test_cli_init_system():
    await init_system()
    # 验证核心指数和 ETF 已经被注册入库
    symbols = meta_db.list_symbols(is_benchmark=True)
    assert len(symbols) >= 5
    sym_codes = [s["symbol"] for s in symbols]
    assert "000300.SH.IDX" in sym_codes
    assert "SPX.US.IDX" in sym_codes
    assert "510300.SH.ETF" in sym_codes

def test_cli_disk_check(capsys):
    show_disk()
    captured = capsys.readouterr()
    assert "50GB 存储水位与监控现状" in captured.out
    assert "cache_size_gb" in captured.out
