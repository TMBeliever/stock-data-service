import sqlite3
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from config import settings
from core.models import SymbolInfo, Market, AssetType

class MetadataDB:
    def __init__(self, db_path: Path = settings.META_DB_PATH):
        self.db_path = db_path
        self.init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # WAL 模式: 并发读写安全，避免 'database is locked' 错误
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def init_db(self):
        """初始化轻量 SQLite 底座表结构"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            
            # 1. 全球标的代码元数据表
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS symbols (
                symbol TEXT PRIMARY KEY,
                ticker TEXT NOT NULL,
                market TEXT NOT NULL,
                asset_type TEXT NOT NULL,
                name TEXT NOT NULL,
                currency TEXT DEFAULT 'CNY',
                is_benchmark INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                extra_info TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # 2. 全球交易日历表
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS trading_calendars (
                market TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                is_open INTEGER DEFAULT 1,
                open_utc_ms INTEGER,
                close_utc_ms INTEGER,
                PRIMARY KEY (market, trade_date)
            );
            """)

            # 3. 本地 Parquet 缓存追踪表 (供 LRU 磁盘气阀使用)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS cache_access_logs (
                symbol TEXT NOT NULL,
                period TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_size_bytes INTEGER DEFAULT 0,
                covered_start_date TEXT,
                covered_end_date TEXT,
                min_timestamp INTEGER,
                max_timestamp INTEGER,
                row_count INTEGER DEFAULT 0,
                hit_count INTEGER DEFAULT 1,
                last_accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (symbol, period)
            );
            """)

            # 4. 指数成分股与权重表 (宽基指数增强与池过滤)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS index_constituents (
                index_symbol TEXT NOT NULL,
                stock_symbol TEXT NOT NULL,
                weight REAL DEFAULT 0.0,
                in_date TEXT,
                out_date TEXT,
                PRIMARY KEY (index_symbol, stock_symbol, in_date)
            );
            """)

            # 5. 标的级空数据验证记录 (防针对个股停牌/缺数据的无限重复拉取，与全市场日历严格解耦，支持 TTL 重新验证)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS symbol_no_data_records (
                symbol TEXT NOT NULL,
                period TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (symbol, period, trade_date)
            );
            """)
            # 兼容旧表升级：检查并补充 updated_at 字段
            cols = [c[1] for c in cursor.execute("PRAGMA table_info(symbol_no_data_records)").fetchall()]
            if "updated_at" not in cols:
                cursor.execute("ALTER TABLE symbol_no_data_records ADD COLUMN updated_at TEXT;")
                cursor.execute("UPDATE symbol_no_data_records SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL;")

            # 6. 标的别名与大模型解析缓存表 (支持任意非结构化中文别名持久化映射)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS symbol_aliases (
                alias TEXT PRIMARY KEY,
                ticker TEXT NOT NULL,
                market TEXT NOT NULL,
                asset_type TEXT NOT NULL,
                resolved_by TEXT DEFAULT 'llm',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # 创建索引加速检索
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_symbols_market ON symbols(market, asset_type);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_calendar_date ON trading_calendars(market, trade_date);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_cache_accessed ON cache_access_logs(last_accessed_at);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_symbol_no_data ON symbol_no_data_records(symbol, period, trade_date);")
            conn.commit()

    # --- 标的元数据操作 ---
    def upsert_symbol(self, info: SymbolInfo):
        with self._get_conn() as conn:
            conn.execute("""
            INSERT INTO symbols (symbol, ticker, market, asset_type, name, currency, is_benchmark, is_active, extra_info)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                name=excluded.name,
                currency=excluded.currency,
                is_benchmark=excluded.is_benchmark,
                is_active=excluded.is_active,
                extra_info=excluded.extra_info;
            """, (
                info.symbol, info.ticker, info.market.value, info.asset_type.value,
                info.name, info.currency, 1 if info.is_benchmark else 0,
                1 if info.is_active else 0, info.extra_info
            ))
            conn.commit()

    def get_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM symbols WHERE symbol = ?", (symbol,)).fetchone()
            return dict(row) if row else None

    def list_symbols(self, market: Optional[str] = None, asset_type: Optional[str] = None, is_benchmark: Optional[bool] = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM symbols WHERE 1=1"
        params = []
        if market:
            query += " AND market = ?"
            params.append(market)
        if asset_type:
            query += " AND asset_type = ?"
            params.append(asset_type)
        if is_benchmark is not None:
            query += " AND is_benchmark = ?"
            params.append(1 if is_benchmark else 0)
        query += " ORDER BY symbol ASC"
        
        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_alias(self, alias: str) -> Optional[Dict[str, Any]]:
        """查询中文/特殊别名映射"""
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM symbol_aliases WHERE alias = ?", (alias,)).fetchone()
            return dict(row) if row else None

    def upsert_alias(self, alias: str, ticker: str, market: str, asset_type: str, resolved_by: str = "llm"):
        """持久化保存别名解析缓存"""
        with self._get_conn() as conn:
            conn.execute("""
            INSERT INTO symbol_aliases (alias, ticker, market, asset_type, resolved_by)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(alias) DO UPDATE SET
                ticker=excluded.ticker,
                market=excluded.market,
                asset_type=excluded.asset_type,
                resolved_by=excluded.resolved_by;
            """, (alias, ticker, market, asset_type, resolved_by))
            conn.commit()

    # --- 缓存追踪与 LRU 支撑 ---
    def record_cache_access(
        self,
        symbol: str,
        period: str,
        file_path: str,
        file_size_bytes: int,
        covered_start_date: str,
        covered_end_date: str,
        min_ts: int,
        max_ts: int,
        row_count: int
    ):
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            conn.execute("""
            INSERT INTO cache_access_logs (
                symbol, period, file_path, file_size_bytes,
                covered_start_date, covered_end_date,
                min_timestamp, max_timestamp, row_count, hit_count, last_accessed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(symbol, period) DO UPDATE SET
                file_path=excluded.file_path,
                file_size_bytes=excluded.file_size_bytes,
                covered_start_date=excluded.covered_start_date,
                covered_end_date=excluded.covered_end_date,
                min_timestamp=excluded.min_timestamp,
                max_timestamp=excluded.max_timestamp,
                row_count=excluded.row_count,
                hit_count=cache_access_logs.hit_count + 1,
                last_accessed_at=excluded.last_accessed_at;
            """, (
                symbol, period, file_path, file_size_bytes,
                covered_start_date, covered_end_date,
                min_ts, max_ts, row_count, now
            ))
            conn.commit()

    def touch_cache(self, symbol: str, period: str):
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            conn.execute("""
            UPDATE cache_access_logs
            SET hit_count = hit_count + 1, last_accessed_at = ?
            WHERE symbol = ? AND period = ?;
            """, (now, symbol, period))
            conn.commit()

    def get_cache_info(self, symbol: str, period: str) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM cache_access_logs WHERE symbol = ? AND period = ?", (symbol, period)).fetchone()
            return dict(row) if row else None

    def get_lru_candidates(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取最久未访问的缓存条目 (供 LRU 淘汰清理)"""
        with self._get_conn() as conn:
            rows = conn.execute("""
            SELECT * FROM cache_access_logs
            ORDER BY last_accessed_at ASC
            LIMIT ?;
            """, (limit,)).fetchall()
            return [dict(r) for r in rows]

    def remove_cache_record(self, symbol: str, period: str):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM cache_access_logs WHERE symbol = ? AND period = ?", (symbol, period))
            conn.commit()

    def list_cached_symbols(self, period: str = "1d") -> List[str]:
        """获取本地已缓存过的全部标的 symbol 列表"""
        with self._get_conn() as conn:
            rows = conn.execute("SELECT DISTINCT symbol FROM cache_access_logs WHERE period = ?", (period,)).fetchall()
            return [r["symbol"] for r in rows]

    # --- 交易日历操作 ---
    def set_calendar_date(self, market: str, trade_date: str, is_open: bool, open_utc_ms: Optional[int] = None, close_utc_ms: Optional[int] = None, force: bool = False):
        """
        设置/更新交易日历状态。
        状态生命周期准则：
        1. UNKNOWN -> OPEN, UNKNOWN -> CLOSED 正常发生。
        2. OPEN -> CLOSED: 严禁因普通 cache fetch 或未经验证的调用发生！若已是 OPEN，仅当 force=True (如官方日历全量同步) 允许降级。
        3. CLOSED -> OPEN: 必须由包含真实有效行情交易数据的抓取或官方日历更新。
        """
        with self._get_conn() as conn:
            row = conn.execute("SELECT is_open FROM trading_calendars WHERE market = ? AND trade_date = ?", (market, trade_date)).fetchone()
            if row is not None and row["is_open"] == 1 and not is_open and not force:
                # 已经是 OPEN 状态，严禁被降级为 CLOSED
                return

            conn.execute("""
            INSERT INTO trading_calendars (market, trade_date, is_open, open_utc_ms, close_utc_ms)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(market, trade_date) DO UPDATE SET
                is_open=excluded.is_open,
                open_utc_ms=excluded.open_utc_ms,
                close_utc_ms=excluded.close_utc_ms;
            """, (market, trade_date, 1 if is_open else 0, open_utc_ms, close_utc_ms))
            conn.commit()

    # --- 标的级无数据记录操作 (与全市场日历解耦，支持 TTL 自动失效重新验证) ---
    def mark_symbol_no_data(self, symbol: str, period: str, trade_date: str):
        """记录该标的在该日期经外部 Provider 确认无有效交易数据 (如停牌、无交易)，记录并刷新 updated_at 时间戳"""
        with self._get_conn() as conn:
            conn.execute("""
            INSERT INTO symbol_no_data_records (symbol, period, trade_date, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(symbol, period, trade_date) DO UPDATE SET
                updated_at=CURRENT_TIMESTAMP;
            """, (symbol, period, trade_date))
            conn.commit()

    def is_symbol_no_data(self, symbol: str, period: str, trade_date: str, ttl_seconds: Optional[int] = None) -> bool:
        """
        检查该标的在该周期与日期是否已确认为空数据且在 TTL 有效期内。
        若超过 TTL，返回 False，触发 Provider 重新验证。
        """
        ttl = ttl_seconds if ttl_seconds is not None else settings.SYMBOL_NO_DATA_TTL
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT updated_at FROM symbol_no_data_records WHERE symbol = ? AND period = ? AND trade_date = ?",
                (symbol, period, trade_date)
            ).fetchone()
            if not row:
                return False

            raw_time = row["updated_at"]
            try:
                if isinstance(raw_time, str):
                    if "T" in raw_time:
                        dt = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
                    else:
                        dt = datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                elif isinstance(raw_time, datetime):
                    dt = raw_time if raw_time.tzinfo else raw_time.replace(tzinfo=timezone.utc)
                else:
                    return False

                age_seconds = (datetime.now(timezone.utc) - dt).total_seconds()
                if age_seconds > ttl:
                    # TTL 已失效，必须重新请求 Provider 重新验证
                    return False
                return True
            except Exception:
                return False

    def remove_symbol_no_data(self, symbol: str, period: str, trade_date: str):
        """当外部 Provider 成功获取到真实交易数据时，彻底清除该日期的 stale no-data 记录"""
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM symbol_no_data_records WHERE symbol = ? AND period = ? AND trade_date = ?",
                (symbol, period, trade_date)
            )
            conn.commit()

    def clear_symbol_no_data(self, symbol: str, period: Optional[str] = None):
        """清除标的空数据记录 (供强制刷新或全量重同步时使用)"""
        with self._get_conn() as conn:
            if period:
                conn.execute("DELETE FROM symbol_no_data_records WHERE symbol = ? AND period = ?", (symbol, period))
            else:
                conn.execute("DELETE FROM symbol_no_data_records WHERE symbol = ?", (symbol,))
            conn.commit()

    def cleanup_expired_symbol_no_data(self, ttl_seconds: Optional[int] = None) -> int:
        """清理已超期失效的空数据记录，防止数据库膨胀 (供后台清理与 Reconcile 使用)"""
        ttl = ttl_seconds if ttl_seconds is not None else settings.SYMBOL_NO_DATA_TTL
        with self._get_conn() as conn:
            # 兼容 ISO 格式或空格格式的时间戳对比
            cursor = conn.execute("""
            DELETE FROM symbol_no_data_records
            WHERE (strftime('%s', 'now') - strftime('%s', updated_at)) > ?;
            """, (ttl,))
            conn.commit()
            return cursor.rowcount

    def is_trading_day(self, market: str, trade_date: str, default: Optional[bool] = None) -> Optional[bool]:
        """
        判断指定市场与日期是否为交易日。
        量化准则：Unknown != Trading Day
        1. 若数据库已登记：严格返回登记结果 (True/False)
        2. 若未登记：
           - 常规周末(周六、周日)直接判定为 False (非交易日)
           - 工作日因缺乏法定假日/调休真实日历数据，返回 default (默认为 None 表示 UNKNOWN)，严禁默认放行。
        """
        with self._get_conn() as conn:
            row = conn.execute("SELECT is_open FROM trading_calendars WHERE market = ? AND trade_date = ?", (market, trade_date)).fetchone()
            if row is not None:
                return bool(row["is_open"])

        # 检查常规周末 (周六=5, 周日=6)
        try:
            dt = datetime.strptime(trade_date, "%Y-%m-%d")
            if dt.weekday() in (5, 6):
                return False
        except Exception:
            pass

        # 工作日且数据库无日历记录时，返回 UNKNOWN (None)
        return default

    def get_calendar_status(self, market: str, trade_date: str) -> str:
        """返回 'OPEN', 'CLOSED', 或 'UNKNOWN'"""
        val = self.is_trading_day(market, trade_date, default=None)
        if val is True:
            return "OPEN"
        elif val is False:
            return "CLOSED"
        return "UNKNOWN"

meta_db = MetadataDB()
