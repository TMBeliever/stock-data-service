import json
import logging
import re
from typing import Tuple, Optional, Dict
import httpx
from config import settings
from core.database import meta_db

logger = logging.getLogger(__name__)

# 内存级热点字典缓存 (预置主流与高频词)
_MEMORY_RESOLVER_CACHE: Dict[str, Tuple[str, str, str]] = {
    "招商": ("600036", "SH", "STK"),
    "招商银行": ("600036", "SH", "STK"),
    "招行": ("600036", "SH", "STK"),
    "贵州茅台": ("600519", "SH", "STK"),
    "茅台": ("600519", "SH", "STK"),
    "比亚迪": ("002594", "SZ", "STK"),
    "宁德时代": ("300750", "SZ", "STK"),
    "平安银行": ("000001", "SZ", "STK"),
    "中国平安": ("601318", "SH", "STK"),
    "五粮液": ("000858", "SZ", "STK"),
    "长江电力": ("600900", "SH", "STK"),
    "紫金矿业": ("601899", "SH", "STK"),
    "中信证券": ("600030", "SH", "STK"),
    "腾讯": ("00700", "HK", "STK"),
    "腾讯控股": ("00700", "HK", "STK"),
    "阿里巴巴": ("09988", "HK", "STK"),
    "美团": ("03690", "HK", "STK"),
    "沪深300": ("000300", "SH", "IDX"),
    "中证500": ("000905", "SH", "IDX"),
    "中证1000": ("000852", "SH", "IDX"),
    "上证指数": ("000001", "SH", "IDX"),
    "上证50": ("000016", "SH", "IDX"),
    "创业板指": ("399006", "SZ", "IDX"),
    "深证成指": ("399001", "SZ", "IDX"),
    "恒生指数": ("HSI", "HK", "IDX"),
    "纳斯达克": ("NDX", "US", "IDX"),
    "标普500": ("SPX", "US", "IDX"),
    "道琼斯": ("DJI", "US", "IDX"),
}

LLM_TRANSLATION_SYSTEM_PROMPT = (
    "你是一个顶尖金融证券代码解析器。请将输入的任意股票名称、公司简称、ETF或指数转换为标准三段式代码元组。\n"
    "字段要求：\n"
    "- ticker: 纯证券代码 (如 600036, 002371, 00700, AAPL)\n"
    "- market: 市场标识，必须严格为 'SH', 'SZ', 'BJ', 'HK', 'US' 之一\n"
    "- asset_type: 资产类型，必须严格为 'STK', 'ETF', 'IDX' 之一\n"
    "必须仅输出标准 JSON: {\"ticker\": \"...\", \"market\": \"...\", \"asset_type\": \"...\"}，严禁输出任何 Markdown 标记或多余文字。"
)

def _parse_llm_json(content: str) -> Optional[Dict[str, str]]:
    """安全提取大模型返回的 JSON 结构"""
    try:
        clean = content.strip()
        if "{" in clean and "}" in clean:
            clean = clean[clean.find("{"):clean.rfind("}")+1]
        data = json.loads(clean)
        ticker = str(data.get("ticker", "")).strip().upper()
        market = str(data.get("market", "")).strip().upper()
        asset_type = str(data.get("asset_type", "")).strip().upper()
        if ticker and market in ["SH", "SZ", "BJ", "HK", "US"]:
            if asset_type not in ["STK", "ETF", "IDX"]:
                asset_type = "STK"
            return {"ticker": ticker, "market": market, "asset_type": asset_type}
    except Exception as e:
        logger.warning(f"Failed to parse LLM symbol translation output: {content}, error: {e}")
    return None

def resolve_symbol_fallback_llm(name: str) -> Optional[Tuple[str, str, str]]:
    """通过 AI Core 同步请求大模型进行代码识别兜底"""
    url = getattr(settings, "AI_CORE_URL", "http://localhost:8070") + "/api/v1/ai/generate"
    try:
        with httpx.Client(timeout=4.0) as client:
            resp = client.post(
                url,
                json={
                    "system_prompt": LLM_TRANSLATION_SYSTEM_PROMPT,
                    "prompt": name,
                    "temperature": 0.0
                }
            )
            if resp.status_code == 200:
                content = resp.json().get("content", "")
                parsed = _parse_llm_json(content)
                if parsed:
                    return parsed["ticker"], parsed["market"], parsed["asset_type"]
    except Exception as e:
        logger.warning(f"LLM symbol translation failed for '{name}': {e}")
    return None

async def resolve_symbol_fallback_llm_async(name: str) -> Optional[Tuple[str, str, str]]:
    """通过 AI Core 异步请求大模型进行代码识别兜底"""
    url = getattr(settings, "AI_CORE_URL", "http://localhost:8070") + "/api/v1/ai/generate"
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.post(
                url,
                json={
                    "system_prompt": LLM_TRANSLATION_SYSTEM_PROMPT,
                    "prompt": name,
                    "temperature": 0.0
                }
            )
            if resp.status_code == 200:
                content = resp.json().get("content", "")
                parsed = _parse_llm_json(content)
                if parsed:
                    return parsed["ticker"], parsed["market"], parsed["asset_type"]
    except Exception as e:
        logger.warning(f"Async LLM symbol translation failed for '{name}': {e}")
    return None

def resolve_symbol_smart(symbol_str: str) -> Optional[Tuple[str, str, str]]:
    """
    智能符号解析器 (多级加速 + 大模型兜底)：
    1. 内存字典缓存 (0ms)
    2. SQLite 持久化别名表缓存 (<1ms)
    3. 大模型语义翻译 (1-2s，翻译后永久写入内存与 SQLite)
    """
    clean = symbol_str.strip()
    if clean in _MEMORY_RESOLVER_CACHE:
        return _MEMORY_RESOLVER_CACHE[clean]

    # 检查 SQLite 别名表
    row = meta_db.get_alias(clean)
    if row:
        val = (row["ticker"], row["market"], row["asset_type"])
        _MEMORY_RESOLVER_CACHE[clean] = val
        return val

    # 若包含中文字符，或者非纯代码/字母，触发大模型兜底翻译
    has_chinese = bool(re.search(r'[\u4e00-\u9fa5]', clean))
    if has_chinese or ("." not in clean and not clean.isdigit() and len(clean) > 5):
        llm_res = resolve_symbol_fallback_llm(clean)
        if llm_res:
            _MEMORY_RESOLVER_CACHE[clean] = llm_res
            try:
                meta_db.upsert_alias(clean, llm_res[0], llm_res[1], llm_res[2], resolved_by="llm")
            except Exception as e:
                logger.error(f"Failed to cache alias to db: {e}")
            return llm_res

    return None

async def resolve_symbol_smart_async(symbol_str: str) -> Optional[Tuple[str, str, str]]:
    """异步版本智能符号解析"""
    clean = symbol_str.strip()
    if clean in _MEMORY_RESOLVER_CACHE:
        return _MEMORY_RESOLVER_CACHE[clean]

    row = meta_db.get_alias(clean)
    if row:
        val = (row["ticker"], row["market"], row["asset_type"])
        _MEMORY_RESOLVER_CACHE[clean] = val
        return val

    has_chinese = bool(re.search(r'[\u4e00-\u9fa5]', clean))
    if has_chinese or ("." not in clean and not clean.isdigit() and len(clean) > 5):
        llm_res = await resolve_symbol_fallback_llm_async(clean)
        if llm_res:
            _MEMORY_RESOLVER_CACHE[clean] = llm_res
            try:
                meta_db.upsert_alias(clean, llm_res[0], llm_res[1], llm_res[2], resolved_by="llm")
            except Exception as e:
                logger.error(f"Failed to cache alias to db: {e}")
            return llm_res

    return None
