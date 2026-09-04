# Project Instructions for AI

Please follow the rules defined in `.agents/rules/SYSTEM_RULES.md`:
1. **Real Data Only**: No fake/synthetic stock data. Pull from real sources (AkShare, YFinance, etc.).
2. **100% Test Passing**: Every feature must have unit tests, and every unit test must pass.
3. **50GB Storage Ceiling**: Parquet + ZSTD, 100% LazyLoad for individual stocks, dynamic adjustment (Raw + Factor), LRU Sentinel.
4. **Strict UTC timestamps**: All time-series data stored as UTC Epoch Milliseconds.
5. **Unified Symbology**: `[TICKER].[MARKET].[TYPE]`.
