import asyncio
import datetime
import zoneinfo
from typing import List, Tuple, Optional, Dict
import httpx
from core.models import parse_symbol, Market, SnapshotItem

# 港股流通股数缓存 (24小时 TTL)，用于实时计算换手率 volume/floatShares
_HK_FLOAT_SHARES_CACHE: Dict[str, Tuple[float, Optional[float]]] = {}

class SnapshotAdapter:
    """
    跨市场实时股票行情快照提供者 (支持 A股、港股、美股、国内/海外ETF、大盘指数)。
    严格遵循真实性原则 (Real Data Only):
    若外部实时源未开盘、停牌、代码不存在或网络超时，对应标的直接返回 None 并计入 missing 列表，
    绝对不使用历史过期的日K/分钟K假数据进行静默填补。
    """
    def __init__(self, timeout: float = 5.0):
        self.timeout = timeout

    def _symbol_to_provider_key(self, symbol: str) -> Tuple[Optional[str], Optional[str]]:
        """将规范化标的代码 [TICKER].[MARKET].[TYPE] 转换为行情源识别代码"""
        try:
            ticker, market_str, type_str = parse_symbol(symbol)
        except Exception:
            return None, None

        if market_str == Market.SH.value:
            return f"sh{ticker}", symbol
        elif market_str == Market.SZ.value:
            return f"sz{ticker}", symbol
        elif market_str == Market.BJ.value:
            return f"bj{ticker}", symbol
        elif market_str == Market.US.value:
            # 美股行情源要求代码大写
            return f"us{ticker.upper()}", symbol
        elif market_str == Market.HK.value:
            # 港股代码补全为 5 位数字，如 0700 -> 00700, 9988 -> 09988
            hk_ticker = ticker.zfill(5) if ticker.isdigit() else ticker
            return f"hk{hk_ticker}", symbol
        return None, None

    def _parse_timestamp(self, time_str: str, market_prefix: str) -> Optional[int]:
        """将不同市场的本地时间字符串精确转换为严格 UTC 毫秒时间戳"""
        if not time_str:
            return None
        try:
            if market_prefix in ("sh", "sz", "bj"):
                # 格式: 20260903161447 (北京时间 UTC+8)
                if len(time_str) >= 14:
                    dt = datetime.datetime.strptime(time_str[:14], "%Y%m%d%H%M%S").replace(
                        tzinfo=datetime.timezone(datetime.timedelta(hours=8))
                    )
                    return int(dt.astimezone(datetime.timezone.utc).timestamp() * 1000)
            elif market_prefix == "us":
                # 格式: 2026-09-03 11:43:40 (美东时间 America/New_York)
                clean_t = time_str[:19]
                dt = datetime.datetime.strptime(clean_t, "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=zoneinfo.ZoneInfo("America/New_York")
                )
                return int(dt.astimezone(datetime.timezone.utc).timestamp() * 1000)
            elif market_prefix == "hk":
                # 格式: 2026/09/03 16:08:23 (香港时间 UTC+8)
                clean_t = time_str[:19].replace("-", "/")
                dt = datetime.datetime.strptime(clean_t, "%Y/%m/%d %H:%M:%S").replace(
                    tzinfo=datetime.timezone(datetime.timedelta(hours=8))
                )
                return int(dt.astimezone(datetime.timezone.utc).timestamp() * 1000)
        except Exception:
            return None
        return None

    async def _get_hk_float_shares(self, hk_ticker: str) -> Optional[float]:
        """获取港股流通股数(用于计算换手率)，24小时缓存，超时不阻断行情"""
        now = datetime.datetime.now().timestamp()
        cache_key = f"hk:{hk_ticker}"
        if cache_key in _HK_FLOAT_SHARES_CACHE:
            expire_time, val = _HK_FLOAT_SHARES_CACHE[cache_key]
            if now < expire_time:
                return val
            del _HK_FLOAT_SHARES_CACHE[cache_key]

        float_shares = None
        try:
            loop = asyncio.get_running_loop()
            def fetch():
                import yfinance as yf
                # 港股代码格式: 0700.HK (yfinance 要求最少4位，不足补零)
                yf_code = f"{hk_ticker.lstrip('0').zfill(4)}.HK" if hk_ticker.isdigit() else f"{hk_ticker}.HK"
                info = yf.Ticker(yf_code).info
                fs = info.get('floatShares') or info.get('sharesOutstanding')
                return float(fs) if fs else None
            float_shares = await asyncio.wait_for(
                loop.run_in_executor(None, fetch), timeout=3.0
            )
        except Exception:
            pass

        ttl = 86400 if float_shares else 1800
        _HK_FLOAT_SHARES_CACHE[cache_key] = (now + ttl, float_shares)
        return float_shares

    async def fetch_snapshots(self, symbols: List[str]) -> Tuple[List[SnapshotItem], List[str]]:
        """
        批量获取股票实时行情快照:
        返回 (有效快照列表, 未找到/无实时行情标的代码列表)。
        """
        if not symbols:
            return [], []

        key_to_symbol: Dict[str, str] = {}
        missing_symbols: List[str] = []

        for sym in symbols:
            clean_sym = sym.strip()
            if not clean_sym:
                continue
            key, std_sym = self._symbol_to_provider_key(clean_sym)
            if key and std_sym:
                key_to_symbol[key] = std_sym
            else:
                missing_symbols.append(clean_sym)

        if not key_to_symbol:
            return [], missing_symbols

        query_keys = list(key_to_symbol.keys())
        url = f"https://qt.gtimg.cn/q={','.join(query_keys)}"

        raw_text = ""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    raw_text = resp.text
        except Exception as e:
            print(f"[SnapshotAdapter] Warning: snapshot fetch failed: {e}")
            return [], [s.strip() for s in symbols if s.strip()]

        snapshots: List[SnapshotItem] = []
        found_symbols = set()

        for line in raw_text.split(";\n"):
            line = line.strip()
            if not line or "=" not in line:
                continue
            var_name, val = line.split("=", 1)
            key = var_name.replace("v_", "").strip()
            val_clean = val.strip('"; \r\n')
            if not val_clean or val_clean == "1" or "pv_none_match" in var_name:
                continue

            parts = val_clean.split("~")
            if len(parts) < 35:
                continue

            # 匹配对应原始标的代码
            std_sym = key_to_symbol.get(key)
            if not std_sym:
                # 尝试不区分大小写匹配
                for k, s in key_to_symbol.items():
                    if k.lower() == key.lower():
                        std_sym = s
                        break
            if not std_sym:
                continue

            name = parts[1].strip()
            ticker = parts[2].strip()

            def to_float(val_str: str) -> Optional[float]:
                try:
                    if val_str and val_str not in ("None", "", "nan", "--"):
                        return float(val_str)
                except Exception:
                    pass
                return None

            latest_price = to_float(parts[3])
            pre_close = to_float(parts[4])
            open_p = to_float(parts[5])
            high = to_float(parts[33]) if len(parts) > 33 else None
            low = to_float(parts[34]) if len(parts) > 34 else None
            change = to_float(parts[31]) if len(parts) > 31 else None
            pct_change = to_float(parts[32]) if len(parts) > 32 else None

            # 成交量与成交额
            vol = to_float(parts[6])
            amt = None
            if len(parts) > 35 and "/" in parts[35]:
                slash_parts = parts[35].split("/")
                if len(slash_parts) >= 3:
                    amt = to_float(slash_parts[2])
            if amt is None and len(parts) > 37:
                raw_amt = to_float(parts[37])
                if raw_amt is not None:
                    if key.lower().startswith(("sh", "sz", "bj")):
                        amt = round(raw_amt * 10000.0, 2)
                    else:
                        amt = raw_amt

            turnover_rate = to_float(parts[38]) if len(parts) > 38 else None
            # 港股行情源换手率字段恒为 0，改用 volume / floatShares 实时计算
            # 此处先保存 None 占位，待异步补全
            if key.lower().startswith("hk") and (turnover_rate is None or turnover_rate == 0.0):
                turnover_rate = None  # 异步填充标记

            # 提取估值与市值指标 (PE-TTM / 动态PE, PB, 总市值, 流通市值)
            pe = to_float(parts[39]) if len(parts) > 39 else None
            if key.lower().startswith(("sh", "sz", "bj")):
                pb = to_float(parts[46]) if len(parts) > 46 else None
            else:
                pb = to_float(parts[58]) if len(parts) > 58 else None
            total_mv = to_float(parts[45]) if len(parts) > 45 else None
            circ_mv = to_float(parts[44]) if len(parts) > 44 else None

            # 提取股息率 (Dividend Yield %)
            div_yield = None
            if key.lower().startswith(("sh", "sz", "bj")):
                div_yield = to_float(parts[64]) if len(parts) > 64 else None
            elif key.lower().startswith("us"):
                div_yield = to_float(parts[64]) if len(parts) > 64 else None
            elif key.lower().startswith("hk"):
                div_yield = to_float(parts[47]) if len(parts) > 47 else None

            # ETF 实时 IOPV (A股 parts[78])：腾讯行情源对 ETF 在 [78] 位置暴露实时单位净值估算
            nav_val = None
            if key.lower().startswith(("sh", "sz", "bj")) and len(parts) > 78:
                nav_val = to_float(parts[78])

            # 提取真实 UTC 时间戳
            market_prefix = key[:2].lower()
            ts = self._parse_timestamp(parts[30] if len(parts) > 30 else "", market_prefix)

            # 若完全无有效价格与成交，代表该标的无效或无实时数据
            if latest_price is None and pre_close is None:
                continue

            # ETF 折溢价率: (最新价 - NAV) / NAV * 100
            premium_rate = None
            if nav_val and nav_val > 0 and latest_price is not None:
                premium_rate = round((latest_price - nav_val) / nav_val * 100, 4)

            # 五档盘口 (仅 A股行情源在 parts[9:19) 卖档 / parts[19:29) 买档暴露真实挂单价量，
            # 港股/美股该区间恒为 0，严禁伪造为盘口数据，一律置 None)
            ask_prices, ask_volumes, bid_prices, bid_volumes = None, None, None, None
            if key.lower().startswith(("sh", "sz", "bj")) and len(parts) > 28:
                try:
                    a_prices = [to_float(parts[9 + i * 2]) for i in range(5)]
                    a_volumes = [to_float(parts[10 + i * 2]) for i in range(5)]
                    b_prices = [to_float(parts[19 + i * 2]) for i in range(5)]
                    b_volumes = [to_float(parts[20 + i * 2]) for i in range(5)]
                    if any(p for p in a_prices if p):
                        ask_prices, ask_volumes = a_prices, a_volumes
                    if any(p for p in b_prices if p):
                        bid_prices, bid_volumes = b_prices, b_volumes
                except Exception:
                    pass

            item = SnapshotItem(
                symbol=std_sym,
                ticker=ticker,
                name=name,
                latest_price=latest_price,
                pre_close=pre_close,
                open=open_p,
                high=high,
                low=low,
                change=change,
                pct_change=pct_change,
                volume=vol,
                amount=amt,
                turnover_rate=turnover_rate,
                pe=pe,
                pe_ttm=pe,
                pb=pb,
                total_market_cap=total_mv,
                market_cap=total_mv,
                circulating_market_cap=circ_mv,
                float_market_cap=circ_mv,
                dividend_yield=div_yield,
                dividend_yield_pct=div_yield,
                nav=nav_val,
                premium_rate=premium_rate,
                ask_prices=ask_prices,
                ask_volumes=ask_volumes,
                bid_prices=bid_prices,
                bid_volumes=bid_volumes,
                timestamp=ts
            )
            snapshots.append(item)
            found_symbols.add(std_sym)

        # 统计 missing
        for sym in symbols:
            clean_sym = sym.strip()
            if clean_sym and clean_sym not in found_symbols and clean_sym not in missing_symbols:
                missing_symbols.append(clean_sym)

        # 港股换手率补全: volume / floatShares (异步并发，不阻断主流程)
        hk_items = [(i, s) for i, s in enumerate(snapshots)
                    if parse_symbol(s.symbol)[1] == Market.HK.value
                    and s.turnover_rate is None
                    and s.volume is not None]
        if hk_items:
            try:
                hk_float_results = await asyncio.gather(
                    *[self._get_hk_float_shares(s.ticker or parse_symbol(s.symbol)[0])
                      for _, s in hk_items],
                    return_exceptions=True
                )
                for (i, s), fs in zip(hk_items, hk_float_results):
                    if isinstance(fs, (int, float)) and fs > 0 and s.volume:
                        snapshots[i].turnover_rate = round(s.volume / fs * 100, 4)
            except Exception as e:
                print(f"[SnapshotAdapter] HK turnover_rate enrichment skipped: {e}")

        return snapshots, missing_symbols

snapshot_adapter = SnapshotAdapter()
