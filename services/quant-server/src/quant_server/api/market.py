import os
import glob
import sqlite3
import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
import httpx
import polars as pl
from quant_core.config import quant_config
from quant_core.client.data_client import data_client

router = APIRouter()

# 常用预设证券字典库 (提供全市场高频资产极速检索与拼音缩写匹配)
BUILTIN_SYMBOLS: List[Dict[str, Any]] = [
    # 宽基与核心 ETF
    {
        "symbol": "510300.SH.ETF", "ticker": "510300", "market": "SH", "asset_type": "ETF",
        "name": "沪深300 ETF", "pinyin": "HS300", "category": "etf", "tags": ["宽基", "核心龙头"]
    },
    {
        "symbol": "510500.SH.ETF", "ticker": "510500", "market": "SH", "asset_type": "ETF",
        "name": "中证500 ETF", "pinyin": "ZZ500", "category": "etf", "tags": ["宽基", "中盘成长"]
    },
    {
        "symbol": "588000.SH.ETF", "ticker": "588000", "market": "SH", "asset_type": "ETF",
        "name": "科创50 ETF", "pinyin": "KC50", "category": "etf", "tags": ["宽基", "硬科技"]
    },
    {
        "symbol": "159915.SZ.ETF", "ticker": "159915", "market": "SZ", "asset_type": "ETF",
        "name": "创业板 ETF", "pinyin": "CYB", "category": "etf", "tags": ["宽基", "成长先锋"]
    },
    {
        "symbol": "510880.SH.ETF", "ticker": "510880", "market": "SH", "asset_type": "ETF",
        "name": "红利 ETF", "pinyin": "HLETF", "category": "etf", "tags": ["价值", "高股息"]
    },
    {
        "symbol": "512880.SH.ETF", "ticker": "512880", "market": "SH", "asset_type": "ETF",
        "name": "证券 ETF", "pinyin": "ZQETF", "category": "etf", "tags": ["行业", "大金融"]
    },
    {
        "symbol": "512690.SH.ETF", "ticker": "512690", "market": "SH", "asset_type": "ETF",
        "name": "酒 ETF", "pinyin": "JETF", "category": "etf", "tags": ["行业", "大消费"]
    },
    {
        "symbol": "512480.SH.ETF", "ticker": "512480", "market": "SH", "asset_type": "ETF",
        "name": "半导体 ETF", "pinyin": "BDTETF", "category": "etf", "tags": ["行业", "芯片半导体"]
    },
    {
        "symbol": "515030.SH.ETF", "ticker": "515030", "market": "SH", "asset_type": "ETF",
        "name": "新能源车 ETF", "pinyin": "XNYETF", "category": "etf", "tags": ["行业", "新能源"]
    },
    {
        "symbol": "518880.SH.ETF", "ticker": "518880", "market": "SH", "asset_type": "ETF",
        "name": "黄金 ETF", "pinyin": "HJETF", "category": "etf", "tags": ["商品", "避险对冲"]
    },
    {
        "symbol": "513100.SH.ETF", "ticker": "513100", "market": "SH", "asset_type": "ETF",
        "name": "纳斯达克 100ETF", "pinyin": "NSDK", "category": "etf", "tags": ["跨境", "全球科技"]
    },
    {
        "symbol": "513500.SH.ETF", "ticker": "513500", "market": "SH", "asset_type": "ETF",
        "name": "标普500 ETF", "pinyin": "BP500", "category": "etf", "tags": ["跨境", "美股标普"]
    },

    # A股核心蓝筹白马与成长龙头
    {
        "symbol": "600519.SH.STK", "ticker": "600519", "market": "SH", "asset_type": "STK",
        "name": "贵州茅台", "pinyin": "GZMT", "category": "stk", "tags": ["白酒", "消费龙头"]
    },
    {
        "symbol": "300750.SZ.STK", "ticker": "300750", "market": "SZ", "asset_type": "STK",
        "name": "宁德时代", "pinyin": "NDSD", "category": "stk", "tags": ["电池", "新能源龙头"]
    },
    {
        "symbol": "601318.SH.STK", "ticker": "601318", "market": "SH", "asset_type": "STK",
        "name": "中国平安", "pinyin": "ZGPA", "category": "stk", "tags": ["保险", "金融龙头"]
    },
    {
        "symbol": "000858.SZ.STK", "ticker": "000858", "market": "SZ", "asset_type": "STK",
        "name": "五粮液", "pinyin": "WLY", "category": "stk", "tags": ["白酒", "浓香龙头"]
    },
    {
        "symbol": "002594.SZ.STK", "ticker": "002594", "market": "SZ", "asset_type": "STK",
        "name": "比亚迪", "pinyin": "BYD", "category": "stk", "tags": ["整车", "新能源车"]
    },
    {
        "symbol": "600036.SH.STK", "ticker": "600036", "market": "SH", "asset_type": "STK",
        "name": "招商银行", "pinyin": "ZSYH", "category": "stk", "tags": ["银行", "零售之王"]
    },
    {
        "symbol": "600900.SH.STK", "ticker": "600900", "market": "SH", "asset_type": "STK",
        "name": "长江电力", "pinyin": "CJDL", "category": "stk", "tags": ["公用事业", "高股息防御"]
    },
    {
        "symbol": "000001.SZ.STK", "ticker": "000001", "market": "SZ", "asset_type": "STK",
        "name": "平安银行", "pinyin": "PAYH", "category": "stk", "tags": ["银行", "股份制核心"]
    },
    {
        "symbol": "601899.SH.STK", "ticker": "601899", "market": "SH", "asset_type": "STK",
        "name": "紫金矿业", "pinyin": "ZJKY", "category": "stk", "tags": ["有色金属", "铜金龙头"]
    },
    {
        "symbol": "300059.SZ.STK", "ticker": "300059", "market": "SZ", "asset_type": "STK",
        "name": "东方财富", "pinyin": "DFCF", "category": "stk", "tags": ["互联网金融", "券商"]
    },
    {
        "symbol": "600276.SH.STK", "ticker": "600276", "market": "SH", "asset_type": "STK",
        "name": "恒瑞医药", "pinyin": "HRYY", "category": "stk", "tags": ["医药生物", "创新药龙头"]
    },
    {
        "symbol": "002475.SZ.STK", "ticker": "002475", "market": "SZ", "asset_type": "STK",
        "name": "立讯精密", "pinyin": "LXJM", "category": "stk", "tags": ["消费电子", "果链龙头"]
    },
    {
        "symbol": "688981.SH.STK", "ticker": "688981", "market": "SH", "asset_type": "STK",
        "name": "中芯国际", "pinyin": "ZXGJ", "category": "stk", "tags": ["晶圆制造", "半导体龙头"]
    },

    # 港股与美股主流标的
    {
        "symbol": "00700.HK.STK", "ticker": "00700", "market": "HK", "asset_type": "STK",
        "name": "腾讯控股", "pinyin": "TXKG", "category": "hk_us", "tags": ["港股", "互联网龙头"]
    },
    {
        "symbol": "09988.HK.STK", "ticker": "09988", "market": "HK", "asset_type": "STK",
        "name": "阿里巴巴", "pinyin": "ALBB", "category": "hk_us", "tags": ["港股", "电商云计算"]
    },
    {
        "symbol": "03690.HK.STK", "ticker": "03690", "market": "HK", "asset_type": "STK",
        "name": "美团-W", "pinyin": "MT", "category": "hk_us", "tags": ["港股", "本地生活"]
    },
    {
        "symbol": "02800.HK.ETF", "ticker": "02800", "market": "HK", "asset_type": "ETF",
        "name": "盈富基金", "pinyin": "YFJJ", "category": "hk_us", "tags": ["港股", "恒生指数ETF"]
    },
    {
        "symbol": "AAPL.US.STK", "ticker": "AAPL", "market": "US", "asset_type": "STK",
        "name": "苹果 Apple", "pinyin": "PG", "category": "hk_us", "tags": ["美股", "消费电子霸主"]
    },
    {
        "symbol": "NVDA.US.STK", "ticker": "NVDA", "market": "US", "asset_type": "STK",
        "name": "英伟达 NVIDIA", "pinyin": "YWD", "category": "hk_us", "tags": ["美股", "AI算力核心"]
    },
    {
        "symbol": "TSLA.US.STK", "ticker": "TSLA", "market": "US", "asset_type": "STK",
        "name": "特斯拉 Tesla", "pinyin": "TSL", "category": "hk_us", "tags": ["美股", "电动车智驾"]
    },
    {
        "symbol": "SPY.US.ETF", "ticker": "SPY", "market": "US", "asset_type": "ETF",
        "name": "SPDR 标普500ETF", "pinyin": "SPY", "category": "hk_us", "tags": ["美股", "标普500ETF"]
    },
    {
        "symbol": "QQQ.US.ETF", "ticker": "QQQ", "market": "US", "asset_type": "ETF",
        "name": "纳斯达克100 ETF", "pinyin": "QQQ", "category": "hk_us", "tags": ["美股", "纳指100ETF"]
    },
]

def _load_meta_db_symbols() -> List[Dict[str, Any]]:
    """从本地 packages/stock-data/data/metadata/meta.db 读取更多标的元数据补充到索引中"""
    possible_paths = [
        os.path.abspath("packages/stock-data/data/metadata/meta.db"),
        os.path.abspath("../stock-data/data/metadata/meta.db"),
        os.path.abspath("../../packages/stock-data/data/metadata/meta.db"),
        os.path.join(os.path.dirname(__file__), "../../../../../packages/stock-data/data/metadata/meta.db"),
    ]
    db_path = next((p for p in possible_paths if os.path.exists(p)), None)
    if not db_path:
        return []
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT symbol, ticker, market, asset_type, name FROM symbols WHERE is_active = 1")
        rows = cur.fetchall()
        conn.close()
        res = []
        for r in rows:
            sym, ticker, market, asset_type, name = r
            cat = "etf" if asset_type == "ETF" else ("stk" if market in ("SH", "SZ", "BJ") else "hk_us")
            res.append({
                "symbol": sym,
                "ticker": ticker,
                "market": market,
                "asset_type": asset_type,
                "name": name,
                "pinyin": ticker,
                "category": cat,
                "tags": [asset_type, market],
            })
        return res
    except Exception:
        return []

def _fetch_live_snapshots(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    """从基础数据服务或本地存储获取标的的实时/最新行情快照"""
    if not symbols:
        return {}
    results: Dict[str, Dict[str, Any]] = {}
    
    # 1. 尝试调用基础数据服务
    base_url = quant_config.DATA_SERVICE_HTTP.rstrip("/")
    url = f"{base_url}/api/v1/snapshot"
    try:
        # 支持以逗号分隔批量拉取快照
        sym_str = ",".join(symbols[:25])
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(url, params={"symbols": sym_str})
            if resp.status_code == 200:
                items = resp.json().get("data", [])
                for item in items:
                    sym = item.get("symbol")
                    if sym:
                        results[sym] = item
    except Exception:
        pass

    # 2. 对缺失快照的标的，尝试从本地 Parquet 文件的最后几条 Bar 提取最新收盘价和涨跌幅
    for sym in symbols:
        if sym not in results:
            try:
                bars = data_client.get_bars(sym, period="1d", adjust="raw")
                if bars and len(bars) >= 1:
                    last = bars[-1]
                    prev = bars[-2] if len(bars) >= 2 else last
                    chg = last.close - prev.close
                    pct = round((chg / prev.close) * 100, 2) if prev.close > 0 else 0.0
                    results[sym] = {
                        "symbol": sym,
                        "ticker": sym.split(".")[0],
                        "name": sym.split(".")[0],
                        "latest_price": round(last.close, 3),
                        "change": round(chg, 3),
                        "pct_change": pct,
                        "open": round(last.open, 3),
                        "high": round(last.high, 3),
                        "low": round(last.low, 3),
                        "pre_close": round(prev.close, 3),
                        "volume": last.volume,
                        "amount": last.amount,
                    }
            except Exception:
                pass

    return results

@router.get("/symbols/search")
def search_symbols(
    q: Optional[str] = Query(None, description="搜索关键词 (支持代码、名称、拼音首字母，如 600519、贵州茅台、GZMT、HS300)"),
    category: Optional[str] = Query(None, description="分类过滤 (all, stk, etf, hk_us)"),
    limit: int = Query(15, ge=1, le=50, description="返回最大数量"),
):
    """
    智能标的模糊检索与联想推荐 (仿同花顺/雪球):
    - 支持股票代码 (600519)、拼音缩写 (GZMT/CYB)、中文名称 (茅台/沪深300);
    - 未输入时返回热门核心推荐;
    - 附带最新行情现价、涨跌幅、估值与市场标签。
    """
    all_symbols_map: Dict[str, Dict[str, Any]] = {}
    for item in BUILTIN_SYMBOLS:
        all_symbols_map[item["symbol"]] = dict(item)

    # 载入本地 meta.db 扩展标的
    for item in _load_meta_db_symbols():
        if item["symbol"] not in all_symbols_map:
            all_symbols_map[item["symbol"]] = item

    all_symbols = list(all_symbols_map.values())

    matched: List[Dict[str, Any]] = []

    keyword = (q or "").strip().upper()

    if not keyword:
        # 空输入：返回热门推荐 (根据 category 筛选)
        if category and category != "all":
            matched = [s for s in all_symbols if s.get("category") == category]
        else:
            matched = all_symbols[:limit]
    else:
        # 1. 匹配已有字典库 (代码精确前缀、名称包含、拼音首字母包含)
        for s in all_symbols:
            sym_u = s["symbol"].upper()
            ticker_u = s.get("ticker", "").upper()
            name_u = s.get("name", "").upper()
            pinyin_u = s.get("pinyin", "").upper()

            is_match = False
            priority = 99

            if ticker_u == keyword:
                is_match = True
                priority = 1
            elif ticker_u.startswith(keyword):
                is_match = True
                priority = 2
            elif sym_u.startswith(keyword):
                is_match = True
                priority = 3
            elif keyword in name_u:
                is_match = True
                priority = 4
            elif keyword in pinyin_u:
                is_match = True
                priority = 5

            if is_match:
                if category and category != "all" and s.get("category") != category:
                    continue
                item_copy = dict(s)
                item_copy["_priority"] = priority
                matched.append(item_copy)

        matched.sort(key=lambda x: x.get("_priority", 99))

        # 2. 智能容错识别：若用户直接输入了一个全市场 6 位代码，且不在内置列表中，动态生成候选项
        if keyword.isdigit() and len(keyword) == 6:
            # 自动推断市场
            if keyword.startswith(("60", "68")):
                auto_sym = f"{keyword}.SH.STK"
                auto_cat = "stk"
                auto_mkt = "SH"
                auto_type = "STK"
            elif keyword.startswith(("00", "30")):
                auto_sym = f"{keyword}.SZ.STK"
                auto_cat = "stk"
                auto_mkt = "SZ"
                auto_type = "STK"
            elif keyword.startswith("51") or keyword.startswith("58"):
                auto_sym = f"{keyword}.SH.ETF"
                auto_cat = "etf"
                auto_mkt = "SH"
                auto_type = "ETF"
            elif keyword.startswith("15") or keyword.startswith("16"):
                auto_sym = f"{keyword}.SZ.ETF"
                auto_cat = "etf"
                auto_mkt = "SZ"
                auto_type = "ETF"
            else:
                auto_sym = f"{keyword}.SH"
                auto_cat = "stk"
                auto_mkt = "SH"
                auto_type = "STK"

            if not any(m["symbol"] == auto_sym or m["ticker"] == keyword for m in matched):
                matched.insert(0, {
                    "symbol": auto_sym,
                    "ticker": keyword,
                    "market": auto_mkt,
                    "asset_type": auto_type,
                    "name": f"A股({keyword})",
                    "pinyin": keyword,
                    "category": auto_cat,
                    "tags": [auto_mkt, auto_type, "全市场直连"],
                })

    # 截断 limit
    candidates = matched[:limit]
    candidate_symbols = [c["symbol"] for c in candidates]

    # 批量补全行情快照
    snapshots = _fetch_live_snapshots(candidate_symbols)

    for c in candidates:
        snap = snapshots.get(c["symbol"])
        if snap:
            c["latest_price"] = snap.get("latest_price")
            c["change"] = snap.get("change")
            c["pct_change"] = snap.get("pct_change")
            c["open"] = snap.get("open")
            c["high"] = snap.get("high")
            c["low"] = snap.get("low")
            c["pre_close"] = snap.get("pre_close")
            c["volume"] = snap.get("volume")
            c["amount"] = snap.get("amount")
            c["pe"] = snap.get("pe")
            c["pb"] = snap.get("pb")
            c["market_cap"] = snap.get("total_market_cap") or snap.get("market_cap")
            if snap.get("name") and (c["name"] == c["ticker"] or c["name"].startswith("A股(")):
                c["name"] = snap["name"]
        else:
            c["latest_price"] = c.get("latest_price", None)
            c["pct_change"] = c.get("pct_change", 0.0)

    return {
        "count": len(candidates),
        "data": candidates
    }

@router.get("/symbols/{symbol}/detail")
def get_symbol_detail(symbol: str):
    """
    获取单个标的的详细行情快照与基本面数据
    """
    sym = symbol.strip().upper()
    # 查找内置或构造
    meta = next((s for s in BUILTIN_SYMBOLS if s["symbol"] == sym or s["ticker"] == sym), None)
    if not meta:
        # 尝试拆解
        parts = sym.split(".")
        ticker = parts[0]
        market = parts[1] if len(parts) > 1 else "SH"
        asset_type = parts[2] if len(parts) > 2 else ("ETF" if ticker.startswith(("51", "15")) else "STK")
        meta = {
            "symbol": sym,
            "ticker": ticker,
            "market": market,
            "asset_type": asset_type,
            "name": ticker,
            "category": "etf" if asset_type == "ETF" else "stk",
            "tags": [market, asset_type],
        }

    snaps = _fetch_live_snapshots([sym])
    snap = snaps.get(sym, {})

    res = dict(meta)
    res.update(snap)
    if not res.get("name") or res["name"] == res.get("ticker"):
        if snap.get("name"):
            res["name"] = snap["name"]

    return {
        "symbol": sym,
        "detail": res
    }

@router.get("/symbols/{symbol}/kline")
def get_symbol_kline(
    symbol: str,
    period: str = Query("1d", description="K线周期 (1d)"),
    adjust: str = Query("qfq", description="复权类型 (qfq, raw, hfq)"),
    limit: int = Query(180, ge=10, le=800, description="K线根数限制"),
):
    """
    获取单个标的的日 K 线数据，自动计算 MA5, MA10, MA20 均线与成交量，
    专供 ECharts Candlestick 烛台图渲染
    """
    sym = symbol.strip().upper()
    bars = data_client.get_bars(sym, period=period, adjust=adjust)
    if not bars:
        # 降级尝试 raw
        bars = data_client.get_bars(sym, period=period, adjust="raw")

    if not bars:
        return {
            "symbol": sym,
            "period": period,
            "count": 0,
            "data": []
        }

    # 截取最近 limit 根
    sliced_bars = bars[-limit:] if len(bars) > limit else bars

    closes = [b.close for b in sliced_bars]
    kline_list = []

    for i, b in enumerate(sliced_bars):
        # 均线计算
        ma5 = sum(closes[max(0, i - 4):i + 1]) / len(closes[max(0, i - 4):i + 1]) if i >= 4 else None
        ma10 = sum(closes[max(0, i - 9):i + 1]) / len(closes[max(0, i - 9):i + 1]) if i >= 9 else None
        ma20 = sum(closes[max(0, i - 19):i + 1]) / len(closes[max(0, i - 19):i + 1]) if i >= 19 else None

        dt_str = datetime.datetime.fromtimestamp(b.timestamp / 1000, tz=datetime.timezone.utc).strftime("%Y-%m-%d")

        kline_list.append({
            "timestamp": b.timestamp,
            "date": dt_str,
            "open": round(b.open, 3),
            "close": round(b.close, 3),
            "low": round(b.low, 3),
            "high": round(b.high, 3),
            "volume": b.volume,
            "amount": b.amount,
            "ma5": round(ma5, 3) if ma5 is not None else None,
            "ma10": round(ma10, 3) if ma10 is not None else None,
            "ma20": round(ma20, 3) if ma20 is not None else None,
        })

    return {
        "symbol": sym,
        "period": period,
        "count": len(kline_list),
        "data": kline_list
    }
