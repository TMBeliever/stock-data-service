"""Transparent Data Hub Router for packages/stock-data.

Enables dynamically cataloging, invoking, and caching 1000+ financial datasets
from third-party providers (AkShare, BaoStock, Yahoo Finance) with automatic
Parquet lakehouse persistence and real-time bypass capabilities.
"""

import os
import sys
import json
import time
import inspect
import hashlib
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field
import polars as pl
import pandas as pd
import akshare as ak

router = APIRouter(prefix="/v1/hub", tags=["Universal Financial Data Hub"])

# API 自省编目缓存
_CATALOG_CACHE: Dict[str, Dict[str, Any]] = {}
_CATEGORIES = {
    "valuation": ["valuation", "pe", "pb", "roe", "value", "indicator", "估值", "市盈率", "市净率"],
    "kline": ["hist", "daily", "kline", "min", "weekly", "monthly", "行情", "日线", "分时"],
    "financial": ["financial", "balance", "profit", "cash", "report", "财务", "资产负债", "利润", "现金流"],
    "macro": ["macro", "cpi", "ppi", "gdp", "money", "rate", "宏观", "利率", "通胀"],
    "index": ["index", "constituent", "指数", "成分股", "权重"],
    "fund": ["fund", "etf", "lof", "基金", "净值"],
}


def _classify_api(name: str, doc: str) -> str:
    combined = f"{name} {doc}".lower()
    for cat, keywords in _CATEGORIES.items():
        if any(kw in combined for kw in keywords):
            return cat
    return "valuation"


def _ensure_catalog():
    if _CATALOG_CACHE:
        return
    for name, func in inspect.getmembers(ak, inspect.isfunction):
        if name.startswith("_"):
            continue
        try:
            sig = inspect.signature(func)
            params = []
            for p_name, p in sig.parameters.items():
                if p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                    continue
                req = (p.default == inspect.Parameter.empty)
                d_val = None if req else p.default
                if d_val is not None and not isinstance(d_val, (str, int, float, bool)):
                    d_val = str(d_val)
                params.append({"name": p_name, "required": req, "default": d_val})

            doc = (inspect.getdoc(func) or "").strip()
            summary = doc.split("\n")[0].strip() if doc else name
            category = _classify_api(name, doc)

            _CATALOG_CACHE[f"akshare:{name}"] = {
                "provider": "akshare",
                "api_name": name,
                "summary": summary,
                "category": category,
                "parameters": params,
                "param_count": len(params),
                "docstring": doc,
            }
        except Exception:
            continue


# 存储湖仓根路径
HUB_STORAGE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../data/hub"))
os.makedirs(HUB_STORAGE_DIR, exist_ok=True)


class InvokeRequest(BaseModel):
    params: Dict[str, Any] = Field(default_factory=dict, description="调用参数字典")
    force_refresh: bool = Field(default=False, description="是否强制穿透三方刷新")
    bypass_cache: bool = Field(default=False, description="是否纯实时穿透不缓存")
    limit: int = Field(default=5000, description="最多返回记录行数")


@router.get("/providers")
def list_providers():
    return {"providers": [{"name": "akshare", "description": "AkShare 金融数据接口库", "status": "active"}]}


@router.get("/catalog")
def search_catalog(
    q: Optional[str] = Query(None, description="搜索关键词"),
    category: Optional[str] = Query(None, description="按业务分类"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    _ensure_catalog()
    items = list(_CATALOG_CACHE.values())
    if category:
        items = [it for it in items if it["category"] == category]
    if q:
        q_lower = q.lower()
        items = [
            it for it in items
            if q_lower in it["api_name"].lower() or q_lower in it["summary"].lower()
        ]
    total = len(items)
    page_items = items[offset:offset + limit]
    clean_items = [
        {
            "provider": it["provider"],
            "api_name": it["api_name"],
            "summary": it["summary"],
            "category": it["category"],
            "param_count": it["param_count"],
            "parameters": it["parameters"],
        }
        for it in page_items
    ]
    return {"total": total, "count": len(clean_items), "offset": offset, "limit": limit, "items": clean_items}


@router.get("/catalog/{provider}/{api_name}")
def get_api_detail(provider: str, api_name: str):
    _ensure_catalog()
    key = f"{provider}:{api_name}"
    if key not in _CATALOG_CACHE:
        raise HTTPException(status_code=404, detail=f"API {key} not found in catalog")
    return _CATALOG_CACHE[key]


@router.post("/invoke/{provider}/{api_name}")
def invoke_api(provider: str, api_name: str, req: InvokeRequest):
    if provider != "akshare":
        raise HTTPException(status_code=400, detail=f"Provider {provider} not supported on this node")

    if not hasattr(ak, api_name):
        raise HTTPException(status_code=404, detail=f"API akshare:{api_name} does not exist")

    # 1. 纯实时穿透判断
    is_realtime = req.bypass_cache or any(k in api_name.lower() for k in ["spot", "quote", "realtime"])

    # 2. 缓存指纹与路径
    raw_str = f"{provider}:{api_name}:{json.dumps(req.params, sort_keys=True)}"
    cache_key = hashlib.sha256(raw_str.encode()).hexdigest()[:20]
    api_dir = os.path.join(HUB_STORAGE_DIR, provider, api_name)
    os.makedirs(api_dir, exist_ok=True)
    parquet_path = os.path.join(api_dir, f"{cache_key}.parquet")

    # 3. 缓存命中逻辑
    t0 = time.perf_counter()
    if not is_realtime and not req.force_refresh and os.path.exists(parquet_path):
        try:
            df = pl.read_parquet(parquet_path)
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            records = df.head(req.limit).to_dicts()
            return {
                "status": "success",
                "provider": provider,
                "api_name": api_name,
                "from_cache": True,
                "bypassed_cache": False,
                "cache_key": cache_key,
                "row_count": len(df),
                "returned_count": len(records),
                "columns": df.columns,
                "data": records,
                "elapsed_ms": elapsed_ms,
            }
        except Exception:
            pass

    # 4. 穿透抓取
    func = getattr(ak, api_name)
    try:
        raw_res = func(**req.params)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Upstream provider error: {str(e)}")

    if isinstance(raw_res, pd.DataFrame):
        df = pl.from_pandas(raw_res)
    elif isinstance(raw_res, pl.DataFrame):
        df = raw_res
    elif isinstance(raw_res, list):
        df = pl.DataFrame(raw_res)
    else:
        df = pl.DataFrame({"result": [str(raw_res)]})

    # 5. 落盘湖仓 (若纯实时则绝不落盘)
    if not is_realtime and not df.is_empty():
        try:
            df.write_parquet(parquet_path, compression="zstd")
        except Exception:
            pass

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
    records = df.head(req.limit).to_dicts()
    return {
        "status": "success",
        "provider": provider,
        "api_name": api_name,
        "from_cache": False,
        "bypassed_cache": is_realtime,
        "cache_key": cache_key,
        "row_count": len(df),
        "returned_count": len(records),
        "columns": df.columns,
        "data": records,
        "elapsed_ms": elapsed_ms,
    }
