import asyncio
import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from config import settings
from core.models import SymbolInfo, KlinePeriod, Market, AssetType, parse_symbol, format_symbol
from core.database import meta_db
from core.time import market_timezone
from storage.parquet_manager import parquet_mgr
from storage.sentinel import sentinel

class DailyScheduler:
    """
    盘后轻量级自动化预热与增量同步调度器:
    - 每天盘后 (A股 16:30 / 美股 06:00) 自动同步本地已缓存的股票池
    - 自动补齐缺失最新一根日K
    - 自动触发 50GB 磁盘安全水位巡检与 LRU 淘汰
    """
    def __init__(self):
        self.is_running = False
        self._last_sync_date: Optional[str] = None
        self._last_sync_dates: Dict[str, str] = {}

    def get_watchlist(self, market: Optional[Market] = None) -> List[SymbolInfo]:
        """获取所有需要定时自动保鲜的资产: 核心基准 + 本地已缓存过的股票，可按市场过滤"""
        watchlist = []
        seen_symbols = set()

        # 1. 核心基准资产 (沪深300, 标普500, SPY, QQQ, 300ETF 等)
        benchmarks = meta_db.list_symbols(is_benchmark=True)
        for b in benchmarks:
            ticker, m, t = parse_symbol(b["symbol"])
            market_enum = Market(m)
            if market and market_enum != market:
                continue
            info = SymbolInfo(
                symbol=b["symbol"],
                ticker=ticker,
                market=market_enum,
                asset_type=AssetType(t),
                name=b["name"],
                currency=b["currency"],
                is_benchmark=True
            )
            watchlist.append(info)
            seen_symbols.add(b["symbol"])

        # 2. 本地已缓存过的自选个股 (从 SQLite 元数据权威读取 + 递归扫描补充)
        cached_syms = meta_db.list_cached_symbols(period=KlinePeriod.D1.value)
        for sym in cached_syms:
            if sym not in seen_symbols:
                try:
                    ticker, m, t = parse_symbol(sym)
                    market_enum = Market(m)
                    if market and market_enum != market:
                        continue
                    sym_record = meta_db.get_symbol(sym)
                    name = sym_record["name"] if sym_record else ticker
                    curr = sym_record["currency"] if sym_record else "CNY"
                    info = SymbolInfo(
                        symbol=sym,
                        ticker=ticker,
                        market=market_enum,
                        asset_type=AssetType(t),
                        name=name,
                        currency=curr,
                        is_benchmark=False
                    )
                    watchlist.append(info)
                    seen_symbols.add(sym)
                except Exception:
                    pass

        # 兜底：若有未入库的磁盘文件，递归扫描并解析
        cache_dir = settings.DATA_PATH / "cache_kline" / "daily"
        if cache_dir.exists():
            for p in cache_dir.rglob("*.parquet"):
                # 文件结构如 cache_kline/daily/SH/600519_STK.parquet
                stem = p.stem
                market_name = p.parent.name
                if "_" in stem and market_name in [m.value for m in Market]:
                    ticker_part, type_part = stem.split("_", 1)
                    canonical_sym = f"{ticker_part}.{market_name}.{type_part}"
                else:
                    canonical_sym = stem

                if canonical_sym not in seen_symbols:
                    try:
                        ticker, m, t = parse_symbol(canonical_sym)
                        market_enum = Market(m)
                        if market and market_enum != market:
                            continue
                        sym_record = meta_db.get_symbol(canonical_sym)
                        name = sym_record["name"] if sym_record else ticker
                        curr = sym_record["currency"] if sym_record else "CNY"
                        info = SymbolInfo(
                            symbol=canonical_sym,
                            ticker=ticker,
                            market=market_enum,
                            asset_type=AssetType(t),
                            name=name,
                            currency=curr,
                            is_benchmark=False
                        )
                        watchlist.append(info)
                        seen_symbols.add(canonical_sym)
                    except Exception:
                        pass

        return watchlist

    async def sync_watchlist(self, market: Optional[Market] = None) -> Dict[str, Any]:
        """执行全量或指定市场的活跃池增量更新与断层修补"""
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        
        # 针对不同市场确定当地交易日自然日期
        local_tz = market_timezone(market or Market.SH)
        today_str = now_utc.astimezone(local_tz).strftime("%Y-%m-%d")
        watchlist = self.get_watchlist(market=market)
        success_count = 0
        fail_count = 0

        target_name = market.value if market else "ALL"
        print(f"[DailyScheduler] Starting sync for {len(watchlist)} {target_name} watchlist symbols up to {today_str}...")

        for info in watchlist:
            try:
                # 检查最近已覆盖日期
                cache_rec = meta_db.get_cache_info(info.symbol, KlinePeriod.D1.value)
                covered_end = cache_rec["covered_end_date"] if cache_rec and cache_rec.get("covered_end_date") else None
                
                # 若已覆盖至当天，直接视为最新成功，避免无效外部请求
                if covered_end and covered_end >= today_str:
                    success_count += 1
                    continue

                # 若有断层且截止日期小于今天，增量补齐
                start_req = covered_end or "2024-01-01"
                df = await parquet_mgr.get_or_fetch(info, KlinePeriod.D1, start_req, today_str)
                if df is not None and not df.is_empty():
                    success_count += 1
                else:
                    fail_count += 1
                # 避免高频撞击外部 API
                await asyncio.sleep(0.05)
            except Exception as e:
                print(f"[DailyScheduler] Error syncing {info.symbol}: {e}")
                fail_count += 1

        # 同步后执行一次磁盘巡检与 LRU 维护
        sentinel.check_and_evict()
        storage_status = sentinel.get_storage_stats()
        self._last_sync_date = today_str

        print(f"[DailyScheduler] {target_name} sync finished: {success_count} success, {fail_count} failed. Storage safe: {storage_status['is_safe']}")
        return {
            "market": target_name,
            "sync_date": today_str,
            "total_watchlist": len(watchlist),
            "success": success_count,
            "failed": fail_count,
            "storage_status": storage_status
        }

    async def run_daemon(self):
        """后台常驻定时守护循环：分市场按本地交易所收盘时区独立调度触发"""
        self.is_running = True
        print("[DailyScheduler] Multi-market background daemon started.")
        while self.is_running:
            try:
                now_utc = datetime.datetime.now(datetime.timezone.utc)
                
                # 1. A 股收盘调度 (北京时间 15:30，自动排除周末)
                now_sh = now_utc.astimezone(market_timezone(Market.SH))
                date_sh = now_sh.strftime("%Y-%m-%d")
                if now_sh.weekday() not in (5, 6) and ((now_sh.hour == 15 and now_sh.minute >= 30) or now_sh.hour > 15):
                    if self._last_sync_dates.get("A_SHARE") != date_sh:
                        self._last_sync_dates["A_SHARE"] = date_sh
                        await self.sync_watchlist(market=Market.SH)
                        await self.sync_watchlist(market=Market.SZ)

                # 2. 港股收盘调度 (香港时间 16:30，自动排除周末)
                now_hk = now_utc.astimezone(market_timezone(Market.HK))
                date_hk = now_hk.strftime("%Y-%m-%d")
                if now_hk.weekday() not in (5, 6) and ((now_hk.hour == 16 and now_hk.minute >= 30) or now_hk.hour > 16):
                    if self._last_sync_dates.get("HK") != date_hk:
                        self._last_sync_dates["HK"] = date_hk
                        await self.sync_watchlist(market=Market.HK)

                # 3. 美股收盘调度 (美东时间 16:30，自动考虑夏令时与冬令时，自动排除周末)
                now_us = now_utc.astimezone(market_timezone(Market.US))
                date_us = now_us.strftime("%Y-%m-%d")
                if now_us.weekday() not in (5, 6) and ((now_us.hour == 16 and now_us.minute >= 30) or now_us.hour > 16):
                    if self._last_sync_dates.get("US") != date_us:
                        self._last_sync_dates["US"] = date_us
                        await self.sync_watchlist(market=Market.US)

                await asyncio.sleep(60) # 每分钟检查一次
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[DailyScheduler] Daemon error: {e}")
                await asyncio.sleep(60)

scheduler = DailyScheduler()
