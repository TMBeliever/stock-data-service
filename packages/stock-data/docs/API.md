# 全球股票数据服务 (Global Stock Data Service) - API 接口文档

本项目为面向股票分析、量化交易与策略回测提供高效、轻量的数据支撑。系统严格适配 **50GB 磁盘限制**，全量支持 **股票 (STK)、宽基指数 (IDX)、ETF 基金 (ETF)** 等资产。

* **在线 Swagger UI 文档**：启动服务后访问 `http://localhost:8000/docs`
* **OpenAPI 3.1 规范文件**：[docs/openapi.json](file:///Users/l/files/self/stock-data/docs/openapi.json)

---

## 1. 全局设计规范与约定

### 1.1 统一标的代码格式 (Symbology)
标的代码采用三段式规范格式：`[TICKER].[MARKET].[TYPE]`

| 组成部分 | 可选值 | 说明与示例 |
| :--- | :--- | :--- |
| **TICKER** | 原始代码 | 字母或数字代码，如 `600519`、`AAPL`、`000300`、`SPY` |
| **MARKET** | `SH`, `SZ`, `BJ`, `US`, `HK` | 交易所/市场归属 |
| **TYPE** | `STK`, `IDX`, `ETF`, `FX`, `CRYPTO` | 资产类别：股票、指数、ETF基金、外汇、加密货币 |

* **示例**：
  * A股股票：`600519.SH.STK` (贵州茅台)
  * 美股股票：`AAPL.US.STK` (苹果)
  * 宽基指数：`000300.SH.IDX` (沪深300)、`SPX.US.IDX` (标普500)
  * ETF基金：`510300.SH.ETF` (300ETF)、`SPY.US.ETF` (标普500ETF)

> *注：接口支持简写输入（如 `600519.SH` 或 `AAPL`），系统会自动推断补全为标准格式。*

### 1.2 时间戳与时区规范
* **内部及接口一律采用 UTC 毫秒时间戳 (`timestamp: int64`)**。
* 严禁混淆本地时区，消除夏令时/冬令时切换产生的时间断层问题。

### 1.3 动态复权规则 (Adjust)
底层只存储原始未复权价（Raw Price）和除权因子（Factor），读时利用 DuckDB 极速计算：
* `raw`：原始未复权价格（默认）。
* `qfq`：前复权价格（以最新交易日为基准向上折算历史，适合技术指标分析与回测）。
* `hfq`：后复权价格（以首日上市为基准向下折算，保持历史走势真实累计回报）。

---

## 2. API 接口详述

### 2.1 获取 K 线时序数据 (支持 LazyLoad 与动态复权)

* **接口路径**：`GET /api/v1/kline`
* **功能描述**：
  * 请求指定标的的历史 K 线。
  * **100% 纯 LazyLoad**：若本地未缓存，网关通过 SingleFlight 防击穿锁向外部源实时拉取并压缩落地为 Parquet，后续查询走极速本地缓存（< 20ms）。
  * **Smart Append**：自动识别断层区间，仅增量拉取缺失部分，无感拼接。
  * **动态重采样**：底层存 1m 线，支持动态聚合为 5m、15m、30m、60m 线。
  * **ETF 专属指标**：若为 ETF 基金，动态附加 `nav` (单位净值) 和 `premium_rate` (折溢价率)。

#### 请求参数 (Query Parameters)
| 参数名 | 类型 | 必填 | 默认值 | 允许值 | 描述 |
| :--- | :--- | :---: | :---: | :--- | :--- |
| `symbol` | string | **是** | - | `AAPL.US.STK`, `600519.SH.STK` 等 | 标的代码 (支持简写推断) |
| `period` | string | 否 | `1d` | `1m`, `5m`, `15m`, `30m`, `60m`, `1d`, `1w`, `1M` | K线周期 |
| `start` | string | 否 | 动态 | 格式 `YYYY-MM-DD` | 起始日期 (日K默认前1年，分钟线默认前5天) |
| `end` | string | 否 | 当天 | 格式 `YYYY-MM-DD` | 截止日期 |
| `adjust` | string | 否 | `raw` | `raw`, `qfq`, `hfq` | 复权类型 |
| `indicators` | string | 否 | `None` | `MA,MACD,RSI,BOLL,ATR,ALL` | 常用量化技术指标向量化计算追加 (均线/布林带/MACD/RSI/ATR) |

#### 请求示例
```bash
# 1. 获取贵州茅台前复权日K
curl -X GET "http://localhost:8000/api/v1/kline?symbol=600519.SH.STK&adjust=qfq&start=2024-01-01&end=2024-01-15"

# 2. 获取标普500 ETF (SPY) 的 5分钟K线
curl -X GET "http://localhost:8000/api/v1/kline?symbol=SPY.US.ETF&period=5m"
```

#### 响应结构 (JSON)
```json
{
  "symbol": "600519.SH.STK",
  "period": "1d",
  "adjust": "qfq",
  "count": 10,
  "data": [
    {
      "timestamp": 1704178800000,
      "open": 1715.0,
      "high": 1718.19,
      "low": 1698.0,
      "close": 1700.0,
      "volume": 3180000.0,
      "amount": 5440083000.0,
      "factor": 1.0,
      "nav": null
    }
  ]
}
```

---

### 2.2 获取个股基本面与估值指标 (PE / PB / 总市值 / 股息率)

* **接口路径**：`GET /api/v1/stock/valuation`
* **功能描述**：查询指定个股的真实基本面与估值数据。
  * **A股**：对接真实百度股市通/新浪官方数据源，返回真实市盈率 PE(TTM)、市净率 PB、总市值。
  * **美股/港股**：对接 Yahoo Finance 官方估值与基本面指标。
  * 支持 `include_history=true` 参数一次性拉取近 1 年历史估值走势序列。

#### 请求参数 (Query Parameters)
| 参数名 | 类型 | 必填 | 默认值 | 描述 |
| :--- | :--- | :---: | :---: | :--- |
| `symbol` | string | **是** | - | 标的代码，如 `002594` (比亚迪), `600519` (茅台), `AAPL` (苹果) |
| `include_history` | bool | 否 | `false` | 是否返回近 1 年历史估值走势序列 |

#### 请求示例
```bash
# 查询比亚迪 (002594) 最新基本面估值
curl -X GET "http://localhost:8000/api/v1/stock/valuation?symbol=002594"
```

#### 响应结构 (JSON)
```json
{
  "symbol": "002594.SZ.STK",
  "ticker": "002594",
  "market": "SZ",
  "name": "比亚迪",
  "date": "2026-09-03",
  "currency": "CNY",
  "pe_ttm": 27.04,             // 滚动市盈率 (TTM)
  "pe_static": null,
  "pb": 3.32,                  // 市净率 (PB)
  "market_cap_billion": 7960.23,// 总市值 (亿元)
  "dividend_yield_pct": 0.41,  // 股息率 (%)
  "history": null
}
```

---

### 2.3 标的元数据查询

* **接口路径**：`GET /api/v1/meta/symbols`
* **功能描述**：查询本地已注册的标的代码表。

#### 请求参数 (Query Parameters)
| 参数名 | 类型 | 必填 | 说明 |
| :--- | :--- | :---: | :--- |
| `market` | string | 否 | 过滤市场：`SH`, `SZ`, `US`, `HK` |
| `asset_type`| string | 否 | 过滤资产类型：`STK`, `IDX`, `ETF` |
| `is_benchmark` | bool | 否 | 是否核心基准资产：`true` / `false` |

#### 请求示例
```bash
curl -X GET "http://localhost:8000/api/v1/meta/symbols?market=US&is_benchmark=true"
```

#### 响应结构
```json
[
  {
    "symbol": "SPX.US.IDX",
    "ticker": "SPX",
    "market": "US",
    "asset_type": "IDX",
    "name": "S&P 500 Index",
    "currency": "USD",
    "is_benchmark": 1,
    "is_active": 1,
    "extra_info": null,
    "created_at": "2026-09-03 08:11:27"
  }
]
```

---

### 2.3 交易日历查询

* **接口路径**：`GET /api/v1/meta/calendar`
* **功能描述**：查询指定市场在特定日期是否开市交易。

#### 请求参数 (Query Parameters)
| 参数名 | 类型 | 必填 | 示例 | 说明 |
| :--- | :--- | :---: | :--- | :--- |
| `market` | string | **是** | `US` | 目标市场 |
| `trade_date`| string | **是** | `2026-07-04` | 查询日期 (YYYY-MM-DD) |

#### 响应结构
```json
{
  "market": "US",
  "trade_date": "2026-07-04",
  "is_open": false
}
```

---

### 2.4 50GB 存储水位与监控健康度

* **接口路径**：`GET /api/v1/system/storage`
* **功能描述**：监控磁盘物理占用、Lazy 缓存池水位和系统安全状态。

#### 请求示例
```bash
curl -X GET "http://localhost:8000/api/v1/system/storage"
```

#### 响应结构
```json
{
  "cache_size_gb": 0.05,
  "cache_max_gb": 20.0,
  "cache_usage_ratio": 0.25,
  "benchmark_size_mb": 1.2,
  "meta_db_size_mb": 0.15,
  "host_free_disk_gb": 32.5,
  "host_total_disk_gb": 465.6,
  "is_safe": true
}
```

---

### 2.5 手动触发 LRU 淘汰清理

* **接口路径**：`POST /api/v1/system/evict`
* **功能描述**：立即对 `cache_kline` 目录执行安全巡检，当空间超过限制时，根据最近访问时间（LRU）优先淘汰分钟线与最久未被访问的日K文件。

#### 响应结构
```json
{
  "freed_bytes": 104857600,
  "freed_mb": 100.0,
  "status": "success"
}
```

### 2.6 深度财务报表与比率查询

* **接口路径**：`GET /api/v1/stock/financials`
* **功能描述**：获取上市公司完整的季度/年度财务报表（营收、净利润、总资产、总负债、经营现金流、毛利率、净利率、资产负债率）。
* **参数**：
  * `symbol`: 股票代码，如 `002594`
  * `limit`: 返回近 N 期季报 (默认 8，即最近 2 年)

#### 请求示例
```bash
curl "http://localhost:8000/api/v1/stock/financials?symbol=002594&limit=4"
```

---

### 2.7 市场资金流向与北向资金

* **接口路径**：`GET /api/v1/market/moneyflow`
* **功能描述**：查询今日北向资金（沪股通、深股通）、南向资金净流入额以及市场资金偏好与板块涨跌分布。

#### 请求示例
```bash
curl "http://localhost:8000/api/v1/market/moneyflow"
```

---

### 2.8 宽基指数成分股与核心样本池

* **接口路径**：`GET /api/v1/index/constituents`
* **功能描述**：查询指定宽基指数（如沪深300 `000300`、中证500 `000905` 全量成分股，以及标普500 `SPX` 核心代表性成分股样本），用于限定选股范围或构建量化策略底仓。

#### 请求示例
```bash
curl "http://localhost:8000/api/v1/index/constituents?index_symbol=000300"
```

---

### 2.9 A 股全市场每日截面选股器 (Screener)

* **接口路径**：`GET /api/v1/screener`
* **功能描述**：基于 A 股全市场 5000+ 只股票实时截面行情执行多因子筛选与过滤排序。
* **参数**：
  * `min_pct_change`: 最小涨跌幅 (%)，如 `5.0`
  * `max_pct_change`: 最大涨跌幅 (%)
  * `min_price` / `max_price`: 价格区间过滤
  * `min_amount`: 最低成交额过滤 (元)
  * `limit`: 返回数量上限 (默认 50)

#### 请求示例
```bash
# 选出今日涨幅 >= 8% 的股票排名前 10
curl "http://localhost:8000/api/v1/screener?min_pct_change=8.0&limit=10"
```

---

### 2.10 公司画像与行业分类

* **接口路径**：`GET /api/v1/stock/profile`
* **功能描述**：查询上市公司的官方行业分类、主营业务、上市日期、注册资本与公司简介。

#### 请求示例
```bash
curl "http://localhost:8000/api/v1/stock/profile?symbol=002594"
```

---

### 2.11 股东户数与十大流通股东 (筹码集中度)

* **接口路径**：`GET /api/v1/stock/shareholders`
* **功能描述**：查询最新报告期股东总户数、户均持股数量以及前十大流通股东持股占比与性质。

#### 请求示例
```bash
curl "http://localhost:8000/api/v1/stock/shareholders?symbol=002594"
```

---

### 2.12 全市场行业与概念题材板块行情

* **接口路径**：`GET /api/v1/market/sectors`
* **功能描述**：查询今日全市场行业板块或概念板块（华为汽车、固态电池、低空经济等）的平均涨幅排行与领涨龙头股。
* **参数**：
  * `indicator`: `行业` 或 `概念` (默认 `行业`)
  * `limit`: 返回前 N 个板块 (默认 30)

#### 请求示例
```bash
curl "http://localhost:8000/api/v1/market/sectors?indicator=概念&limit=10"
```

---

### 2.13 每日龙虎榜成交明细

* **接口路径**：`GET /api/v1/market/dragon-tiger`
* **功能描述**：查询今日/指定交易日机构席位与游资上榜股票、涨跌偏离值与上榜原因。

#### 请求示例
```bash
curl "http://localhost:8000/api/v1/market/dragon-tiger"
```

---

### 2.14 宏观基准：国债无风险收益率

* **接口路径**：`GET /api/v1/macro/treasury-yield`
* **功能描述**：获取中美 10 年期国债收益率最新基准走势（用于 DCF 资产折现率与大类资产股债轮动）。

#### 请求示例
```bash
curl "http://localhost:8000/api/v1/macro/treasury-yield"
```

---

### 2.15 实时行情快照：五档买卖盘口

* **接口路径**：`GET /api/v1/snapshot` 与 `POST /api/v1/snapshot/batch`
* **功能描述**：在原有最新价/涨跌幅等基础上，**新增 A 股 Level-1 五档买卖盘口数据**。仅 A 股 (SH/SZ/BJ) 支持五档字段，港股/美股该字段返回 `null`（行情源未披露）。
* **新增响应字段**：
  * `ask_prices`: 卖一到卖五档挂单价格列表 (仅 A 股)
  * `ask_volumes`: 卖一到卖五档挂单量列表 (手)
  * `bid_prices`: 买一到买五档挂单价格列表 (仅 A 股)
  * `bid_volumes`: 买一到买五档挂单量列表 (手)

#### 请求示例
```bash
curl "http://localhost:8000/api/v1/snapshot?symbols=600519.SH.STK"
```

#### 响应结构 (片段)
```json
{
  "symbol": "600519.SH.STK",
  "latest_price": 1329.38,
  "ask_prices": [1329.36, 1329.35, 1329.34, 1329.31, 1329.30],
  "ask_volumes": [2, 2, 4, 2, 23],
  "bid_prices": [1329.38, 1329.69, 1329.70, 1329.86, 1329.89],
  "bid_volumes": [2, 1, 10, 1, 5],
  ...
}
```

> **注**：本接口提供的是 **Level-1 盘口快照** (五档报价)，属于免费行情源已披露的数据。Level-2 逐笔委托/成交流需要交易所付费授权，不在本服务支持范围内。

---

### 2.16 历史分红送配记录

* **接口路径**：`GET /api/v1/stock/dividends`
* **功能描述**：获取标的历史分红送配明细（回测收益序列还原、除权除息日核对的必要基础数据）。
  * **A 股**：对接东方财富分红送配详情，含每股现金分红、送转比例、股权登记日、除权除息日与方案进度。
  * **美股/港股**：对接 Yahoo Finance 官方历史分红序列（每股现金分红金额），源端无送转比例/股权登记日等字段。
* **参数**：
  * `symbol`: 股票代码 (必填)
  * `limit`: 返回最近 N 条历史记录 (默认 20，最大 200)

#### 请求示例
```bash
curl "http://localhost:8000/api/v1/stock/dividends?symbol=600519&limit=10"
```

#### 响应结构
```json
{
  "symbol": "600519.SH.STK",
  "ticker": "600519",
  "market": "SH",
  "currency": "CNY",
  "count": 10,
  "dividends": [
    {
      "report_date": "2023-12-31",
      "announcement_date": "2024-03-29",
      "record_date": "2024-07-18",
      "ex_dividend_date": "2024-07-19",
      "cash_per_share": 3.088,
      "bonus_share_ratio": 0.0,
      "dividend_yield_pct": 2.35,
      "plan_progress": "实施分配",
      "plan_description": "10派30.88元(含税,扣税后28.88元)"
    }
  ]
}
```

---

### 2.17 融资融券：全市场两融走势与个股明细

* **接口路径**：
  * `GET /api/v1/market/margin` — 全市场融资融券每日走势
  * `GET /api/v1/stock/margin` — 个股融资融券明细
* **功能描述**：融资融券余额/买入额是衡量市场做多/做空压力的标准指标。北交所暂无两融业务，对应请求返回 400。

#### 全市场请求示例
```bash
curl "http://localhost:8000/api/v1/market/margin?market=SH&start=2026-09-01&end=2026-09-03"
```

#### 全市场响应结构
```json
{
  "market": "SH",
  "count": 3,
  "data": [
    {
      "date": "2026-09-03",
      "financing_buy": 77603882394.0,
      "financing_balance": 1342763630194.0,
      "securities_lending_volume": 3114846112.0,
      "securities_lending_balance": 18559843637.0,
      "total_balance": 1361323473831.0
    }
  ]
}
```

#### 个股请求示例
```bash
curl "http://localhost:8000/api/v1/stock/margin?symbol=600519"
```

#### 个股响应结构
```json
{
  "symbol": "600519.SH.STK",
  "date": "2026-09-03",
  "found": true,
  "data": {
    "date": "2026-09-03",
    "symbol": "600519.SH.STK",
    "financing_buy": 138924008.0,
    "financing_balance": 17302398388.0,
    "lending_sell_volume": 6700.0,
    "lending_balance_volume": 110419.0,
    "total_balance": null
  }
}
```

> **注**：交易所两融明细通常 T+1 披露，个股查询默认取最近一个交易日。上交所两融明细不含 `total_balance` 合计字段。

---

### 2.18 中国宏观经济核心序列：PMI / CPI / PPI / M2

* **接口路径**：
  * `GET /api/v1/macro/china/pmi` — 制造业/非制造业采购经理人指数 (PMI)
  * `GET /api/v1/macro/china/cpi` — 居民消费价格指数 (CPI) 月度序列
  * `GET /api/v1/macro/china/ppi` — 工业生产者出厂价格指数 (PPI) 月度序列
  * `GET /api/v1/macro/china/m2` — M2 货币供应量同比增速
* **功能描述**：对接国家统计局官方数据，为多因子模型、宏观择时策略提供基础宏观序列。
* **参数**：
  * `limit`: 返回最近 N 期数据 (默认 24)

#### 请求示例
```bash
curl "http://localhost:8000/api/v1/macro/china/pmi?limit=6"
curl "http://localhost:8000/api/v1/macro/china/cpi?limit=6"
curl "http://localhost:8000/api/v1/macro/china/ppi?limit=6"
curl "http://localhost:8000/api/v1/macro/china/m2?limit=6"
```

#### PMI 响应示例
```json
{
  "updated_at": "2026-09-04 10:00:00",
  "count": 3,
  "data": [
    {
      "month": "2026-08",
      "manufacturing_index": 49.8,
      "manufacturing_yoy_pct": 0.81,
      "non_manufacturing_index": 49.0,
      "non_manufacturing_yoy_pct": -2.58
    }
  ]
}
```

> **注**：中国 M2 数据源（金十数据中心）为第三方，可能因源端服务临时不可用而返回 500，此时严禁伪造数据返回。

---

### 2.19 分析师一致预期 (机构盈利预测)

* **接口路径**：`GET /api/v1/stock/analyst-consensus`
* **功能描述**：获取个股机构研报数量、评级分布（买入/增持/中性/减持/卖出）与未来 4 年 EPS 一致预期。仅支持 A 股（SH/SZ），源端东方财富。
* **参数**：
  * `symbol`: 股票代码 (必填，如 `600519`)
  * `market`: 市场标识 (必填，仅 `SH`/`SZ`)
* **缓存策略**：全市场盈利预测表拉取较慢（约 2-4 秒），已对全市场结果做 15 分钟 TTL 一次性内存缓存，同一标的连续查询秒级返回。

#### 请求示例
```bash
curl "http://localhost:8000/api/v1/stock/analyst-consensus?symbol=600519&market=SH"
```

#### 响应结构
```json
{
  "symbol": "600519",
  "data_source": "东方财富 (East Money)",
  "report_count": 45,
  "rating_buy": 36,
  "rating_accumulate": 9,
  "rating_neutral": 0,
  "rating_reduce": 0,
  "rating_sell": 0,
  "eps_forecasts": [
    {"year": 2025, "eps": 65.85},
    {"year": 2026, "eps": 67.66},
    {"year": 2027, "eps": 71.52},
    {"year": 2028, "eps": 75.21}
  ]
}
```

---

## 3. 量化回测直通 SDK (Zero-Copy Python)

对于本地回测或实盘算法，无需通过 HTTP 序列化，可直接通过 Python 调用 `StockDataSDK`，在内存中直接获得 **Polars DataFrame**，读取速度提升 **50 倍** 以上：

```python
from sdk import StockDataSDK

sdk = StockDataSDK()

# 同步调用：获取贵州茅台前复权日K
df = sdk.get_kline(
    symbol="600519.SH.STK",
    period="1d",
    start="2023-01-01",
    end="2024-01-01",
    adjust="qfq",
    indicators=["MA", "MACD", "RSI", "BOLL", "ATR"] # 自动追加常用量化技术指标
)

# 异步调用
# df = await sdk.get_kline_async("SPY.US.ETF", period="5m")

print(df.head())
# 输出标准 Polars DataFrame，包含 timestamp, open, high, low, close, volume, factor, ma5, macd_dif, rsi, boll_mid, atr 等
```

---

## 4. 命令行运维与盘后自动调度 (CLI Reference)

```bash
# 1. 首次部署或初始化底座 (注册全球核心基准宽基指数与 ETF)
./.venv/bin/python cli.py init

# 2. 盘后一键增量同步与自选股池保鲜预热 (支持 crontab 定时调用)
./.venv/bin/python cli.py sync

# 3. 查看 50GB 存储与缓存监控状态
./.venv/bin/python cli.py disk-check

# 4. 手动触发 LRU 清理
./.venv/bin/python cli.py evict

# 5. 重新导出最新 OpenAPI 3.1 架构定义
./.venv/bin/python cli.py gen-docs
```

---

## 5. Docker 容器化一键部署

系统已配备生产级 `Dockerfile` 与 `docker-compose.yml`，宿主机 50GB 存储目录通过卷持久化映射：

```bash
# 一键在后台启动容器
docker compose up -d

# 查看容器日志与健康状态
docker compose logs -f
```

---

## 6. WebSocket 全双工流式推送接口 (WebSocket API)

* **连接地址**：`ws://localhost:8000/ws/market`
* **协议机制**：JSON 文本交互，支持心跳保活、按需订阅与即时查询。

### 客户端指令交互协议

#### 1. 行情订阅 (Subscribe)
客户端发送订阅请求后，服务端会立即将该标的的**最新 1 根日K快照推送下来**，并加入长连接广播池：
```json
// 客户端发送
{
  "action": "subscribe",
  "symbol": "002594",
  "period": "1d"
}

// 服务端返回
{
  "type": "subscribed",
  "symbol": "002594.SZ.STK",
  "period": "1d",
  "latest": {
    "timestamp": 1788390000000,
    "open": 268.0,
    "high": 272.5,
    "low": 266.0,
    "close": 270.8,
    "volume": 12500000.0
  }
}
```

#### 2. 即时行情查询 (Query)
通过 WebSocket 在长连接中以 Zero-Copy 直接取回最新 N 根数据：
```json
// 客户端发送
{
  "action": "query",
  "symbol": "002594",
  "period": "1d",
  "limit": 5
}
```

#### 3. 心跳保活 (Ping/Pong)
```json
// 客户端发送: {"action": "ping"}
// 服务端返回: {"type": "pong", "timestamp": 1788418800000}
```

---

## 7. Model Context Protocol (MCP) AI 原生投研通道

面向 **Claude Desktop**、**Cursor**、**Cline** 等 AI 客户端，将本地数据中台直接注入为 AI 的大模型原生工具库。

### 1. 启动方式
```bash
# 标准 Stdio 模式 (供 AI 客户端子进程直接拉起)
./.venv/bin/python mcp_server.py
```

### 2. 注入 Claude Desktop / Cursor 配置示例 (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "stock-data": {
      "command": "/Users/l/files/self/stock-data/.venv/bin/python",
      "args": ["/Users/l/files/self/stock-data/mcp_server.py"]
    }
  }
}
```

### 3. AI 专属工具库清单 (10 大金融分析 Tools)
1. `get_stock_kline`: 查询前复权/多周期 K 线与技术指标 (MA,MACD,RSI,BOLL,ATR)
2. `get_stock_valuation`: 查询 PE(TTM)、前瞻 PE、PB、市值与股息率
3. `get_stock_financials`: 查询资产负债/利润/现金流核心指标与毛利率（防未来函数）
4. `get_stock_profile`: 查询申万官方行业归类与主营业务
5. `get_stock_shareholders`: 查询股东总数（筹码集中度）与前十大流通股东名单
6. `get_market_sectors`: 查询全市场行业/概念题材涨幅榜与领涨龙头
7. `get_dragon_tiger_list`: 查询每日龙虎榜游资与机构买卖席位
8. `screen_stocks`: 全市场 5000+ 股票多因子截面选股器
9. `get_macro_treasury_yield`: 查询中美 10 年期国债最新无风险利率
10. `get_system_storage_status`: 查询 50GB 存储与系统健康度

---

## 8. 常见 HTTP 状态码与异常

| 状态码 | 含义 | 说明 |
| :--- | :--- | :--- |
| `200 OK` | 请求成功 | 返回标准规范数据 |
| `400 Bad Request` | 参数错误 | 标的代码格式不合法或不存在对应市场/类型 |
| `404 Not Found` | 无数据 | 外部源与本地缓存均未查询到该区间数据 |
| `500 Internal Error` | 服务端异常 | 外部网络异常或计算引擎错误 |

