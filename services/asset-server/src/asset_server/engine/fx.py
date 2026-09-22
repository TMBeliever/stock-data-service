import time
import logging
from typing import Dict
import httpx

logger = logging.getLogger("asset_server.engine.fx")

# 兜底基准汇率 (外币兑人民币 CNY)
DEFAULT_FX_RATES: Dict[str, float] = {
    "CNY": 1.0,
    "RMB": 1.0,
    "USD": 7.20,
    "USDT": 7.20,
    "HKD": 0.92,
    "EUR": 7.80,
    "JPY": 0.048,
    "GBP": 9.15,
    "AUD": 4.70,
    "CAD": 5.25,
    "SGD": 5.40,
}

_cached_fx_rates: Dict[str, float] = dict(DEFAULT_FX_RATES)
_cached_timestamp: float = 0.0
FX_CACHE_TTL_SECONDS: float = 600.0  # 缓存 10 分钟


async def get_fx_rates() -> Dict[str, float]:
    """
    获取最新外币兑人民币 (CNY) 汇率字典。
    带 10 分钟本地缓存，若远程请求失败或超时则优雅降级为兜底基准汇率。
    """
    global _cached_fx_rates, _cached_timestamp

    now = time.time()
    if _cached_timestamp > 0 and (now - _cached_timestamp) < FX_CACHE_TTL_SECONDS:
        return _cached_fx_rates

    url = "https://hq.sinajs.cn/list=fx_susdcny,fx_shkdcny,fx_seurcny,fx_sjpycny,fx_sgbpcny"
    headers = {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}

    try:
        async with httpx.AsyncClient(timeout=3.0, trust_env=False) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                rates = dict(_cached_fx_rates)
                for line in resp.text.splitlines():
                    line = line.strip()
                    if not line or "=" not in line or '"' not in line:
                        continue
                    content = line.split('"')[1]
                    parts = content.split(",")
                    if len(parts) >= 2:
                        try:
                            rate_val = float(parts[1])
                            if rate_val > 0:
                                if "fx_susdcny" in line:
                                    rates["USD"] = rate_val
                                    rates["USDT"] = rate_val
                                elif "fx_shkdcny" in line:
                                    rates["HKD"] = rate_val
                                elif "fx_seurcny" in line:
                                    rates["EUR"] = rate_val
                                elif "fx_sjpycny" in line:
                                    rates["JPY"] = rate_val
                                elif "fx_sgbpcny" in line:
                                    rates["GBP"] = rate_val
                        except (ValueError, IndexError):
                            continue
                _cached_fx_rates = rates
                _cached_timestamp = now
                logger.info("✓ 成功同步最新实时外汇汇率")
                return _cached_fx_rates
    except Exception as e:
        logger.warning(f"拉取实时外汇汇率失败，回退使用缓存/默认汇率: {e}")

    # 若拉取异常，刷新时间戳避免频繁重试
    _cached_timestamp = now
    return _cached_fx_rates


def convert_to_base_cny(amount: float, currency: str, rates: Dict[str, float]) -> float:
    """按指定币种将金额换算为基准本位币 CNY"""
    curr = (currency or "CNY").strip().upper()
    rate = rates.get(curr, 1.0)
    return round(amount * rate, 2)
