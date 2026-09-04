import sys
import asyncio
from core.models import Market, AssetType, SymbolInfo
from core.database import meta_db
from storage.sentinel import sentinel
from adapters.factory import adapter_factory
from storage.parquet_manager import parquet_mgr
from core.models import KlinePeriod

async def init_system():
    print("=== [1/3] 初始化 SQLite 元数据底座 ===")
    meta_db.init_db()
    print("✓ 元数据表就绪")

    print("\n=== [2/3] 注册全球核心宽基与 ETF ===")
    core_benchmarks = [
        # A股指数与ETF
        SymbolInfo(symbol="000300.SH.IDX", ticker="000300", market=Market.SH, asset_type=AssetType.INDEX, name="沪深300指数", currency="CNY", is_benchmark=True),
        SymbolInfo(symbol="000905.SH.IDX", ticker="000905", market=Market.SH, asset_type=AssetType.INDEX, name="中证500指数", currency="CNY", is_benchmark=True),
        SymbolInfo(symbol="510300.SH.ETF", ticker="510300", market=Market.SH, asset_type=AssetType.ETF, name="华泰柏瑞沪深300ETF", currency="CNY", is_benchmark=True),
        # 美股指数与ETF
        SymbolInfo(symbol="SPX.US.IDX", ticker="SPX", market=Market.US, asset_type=AssetType.INDEX, name="标普500指数", currency="USD", is_benchmark=True),
        SymbolInfo(symbol="NDX.US.IDX", ticker="NDX", market=Market.US, asset_type=AssetType.INDEX, name="纳斯达克100指数", currency="USD", is_benchmark=True),
        SymbolInfo(symbol="SPY.US.ETF", ticker="SPY", market=Market.US, asset_type=AssetType.ETF, name="SPDR 标普500ETF", currency="USD", is_benchmark=True),
        SymbolInfo(symbol="QQQ.US.ETF", ticker="QQQ", market=Market.US, asset_type=AssetType.ETF, name="纳斯达克100ETF", currency="USD", is_benchmark=True),
        # 港股指数与ETF
        SymbolInfo(symbol="HSI.HK.IDX", ticker="HSI", market=Market.HK, asset_type=AssetType.INDEX, name="恒生指数", currency="HKD", is_benchmark=True),
        SymbolInfo(symbol="02800.HK.ETF", ticker="02800", market=Market.HK, asset_type=AssetType.ETF, name="盈富基金", currency="HKD", is_benchmark=True),
    ]

    for b in core_benchmarks:
        meta_db.upsert_symbol(b)
        print(f"✓ 注册基准标的: {b.symbol} ({b.name})")

    print("\n=== [3/3] 磁盘健康检查 ===")
    stats = sentinel.get_storage_stats()
    print(f"✓ 缓存占用: {stats['cache_size_gb']} GB / {stats['cache_max_gb']} GB ({stats['cache_usage_ratio']}%)")
    print(f"✓ 宿主机剩余空闲: {stats['host_free_disk_gb']} GB (系统状态: {'安全' if stats['is_safe'] else '告警'})")
    print("\n系统初始化完成！")

def show_disk():
    stats = sentinel.get_storage_stats()
    print("=== 50GB 存储水位与监控现状 ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")

def export_docs():
    import json
    from service.app import app
    from pathlib import Path
    docs_dir = Path("docs")
    docs_dir.mkdir(parents=True, exist_ok=True)
    out_file = docs_dir / "openapi.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(app.openapi(), f, ensure_ascii=False, indent=2)
    print(f"✓ 已成功生成最新 OpenAPI 规范文件: {out_file}")

def main():
    if len(sys.argv) < 2:
        print("用法: python cli.py [init | disk-check | evict | gen-docs | sync | reconcile]")
        return
    cmd = sys.argv[1]
    if cmd == "init":
        asyncio.run(init_system())
    elif cmd == "disk-check":
        show_disk()
    elif cmd == "evict":
        freed = sentinel.check_and_evict()
        print(f"手动清理完成，释放: {freed / (1024**2):.2f} MB")
    elif cmd == "gen-docs":
        export_docs()
    elif cmd == "sync":
        from service.scheduler import scheduler
        res = asyncio.run(scheduler.sync_watchlist())
        print(f"✓ 盘后同步完成: 同步总数 {res['total_watchlist']}, 成功 {res['success']}, 失败 {res['failed']}")
    elif cmd == "reconcile":
        res = parquet_mgr.reconcile_storage_metadata()
        print(f"✓ 存储元数据对齐完成: 清理孤儿记录 {res['cleaned_orphans']} 条, 恢复元数据 {res['restored_records']} 条")
    else:
        print(f"未知命令: {cmd}")

if __name__ == "__main__":
    main()
