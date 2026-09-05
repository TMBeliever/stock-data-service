import datetime
import json
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from common_server.database import get_db
from common_server.models import User, UserStrategy, BacktestRecord, UserWatchlist, UserHolding
from common_server.dependencies import get_current_user

router = APIRouter()

# -------------------------------------------------------------
# 预置初始量化策略模板
# -------------------------------------------------------------
DEFAULT_PRESET_STRATEGIES = [
    {
        "name": "经典双均线趋势策略 (Dual MA)",
        "description": "短期均线金叉做多，死叉平仓避险，经典趋势跟踪范式",
        "symbol": "510300.SH.ETF",
        "code": '''from quant_core.core.base_strategy import BaseStrategy
from quant_core.core.models import Bar

class DualMAStrategy(BaseStrategy):
    """
    经典双均线交叉策略 (Dual Moving Average Cross - QuantCore 2.0 极简范式)：
    - MA(5) 上穿 MA(20) 金叉：以 80% 目标仓位买入建仓；
    - MA(5) 下穿 MA(20) 死叉：全部平仓落袋为安。
    """
    def __init__(self, fast_period: int = 5, slow_period: int = 20):
        super().__init__(name="DualMA", params={"fast": fast_period, "slow": slow_period})
        self.fast = fast_period
        self.slow = slow_period

    def on_bar(self, bar: Bar):
        # 1. 均线金叉开仓 (Golden Cross)
        if bar.cross_over(self.fast, self.slow) and not self.position:
            self.order_target_percent(0.8, reason="金叉开仓")

        # 2. 均线死叉平仓 (Death Cross)
        elif bar.cross_under(self.fast, self.slow) and self.position:
            self.close_position(reason="死叉平仓")
'''
    },
    {
        "name": "动态估值分位数定投 (Smart DCA)",
        "description": "按历史价格分位数动态调权，极度低估时加倍定投，估值过高主动止盈",
        "symbol": "510880.SH.ETF",
        "code": '''from quant_core.core.base_strategy import BaseStrategy
from quant_core.core.models import Bar

class SmartDividendDCAStrategy(BaseStrategy):
    """
    智能估值分位数定投策略 (QuantCore 2.0 极简范式)：
    - 利用 bar.percentile(250) 计算价格历史分位数；
    - 分位数 <= 20% (bar.is_undervalued): 加码 2.0 倍基准金额买入；
    - 分位数 >= 80% (bar.is_overvalued): 减仓 20% 主动止盈防回撤。
    """
    def __init__(self, base_amount: float = 2000.0, window: int = 250):
        super().__init__(name="SmartDCA", params={"base_amount": base_amount, "window": window})
        self.base_amount = base_amount
        self.window = window
        self.bar_counter = 0

    def on_bar(self, bar: Bar):
        self.bar_counter += 1
        # 每 5 个交易日评估一次定投
        if self.bar_counter % 5 != 0:
            return

        pct = bar.percentile(self.window)

        # 1. 极度低估: 加倍定投抄底
        if bar.is_undervalued and self.cash >= self.base_amount * 2:
            qty = int((self.base_amount * 2.0) / bar.close // 100) * 100
            if qty > 0:
                self.buy(qty, reason=f"低估加倍定投(分位{pct:.1%})")

        # 2. 合理估值: 正常定投
        elif pct <= 0.50 and self.cash >= self.base_amount:
            qty = int(self.base_amount / bar.close // 100) * 100
            if qty > 0:
                self.buy(qty, reason=f"合理估值定投(分位{pct:.1%})")

        # 3. 严重高估泡沫: 主动止盈 20%
        elif bar.is_overvalued and self.position.available_quantity >= 500:
            sell_qty = min(self.position.available_quantity, int(self.position.available_quantity * 0.2 // 100) * 100)
            if sell_qty > 0:
                self.sell(sell_qty, reason=f"高估主动止盈(分位{pct:.1%})")
'''
    },
    {
        "name": "动态网格波动套利 (Grid Trading)",
        "description": "在震荡市中利用均价带上下挂单，高抛低吸捕捉微观波动利润",
        "symbol": "510500.SH.ETF",
        "code": '''from quant_core.core.base_strategy import BaseStrategy
from quant_core.core.models import Bar

class GridTradingStrategy(BaseStrategy):
    """
    动态自适应网格策略 (QuantCore 2.0 极简范式)：
    - 初始建立 40% 底仓；
    - 价格下跌超 2.5% 触及网格下轨低吸加仓；
    - 价格上涨超 2.5% 触及网格上轨高抛止盈。
    """
    def __init__(self, step_pct: float = 0.025, base_shares: int = 1000):
        super().__init__(name="GridTrading", params={"step": step_pct, "shares": base_shares})
        self.step_pct = step_pct
        self.base_shares = base_shares
        self.last_trade_price = 0.0

    def on_bar(self, bar: Bar):
        # 1. 初始建底仓
        if self.last_trade_price == 0.0:
            self.order_target_percent(0.4, reason="网格初始化底仓")
            self.last_trade_price = bar.close
            return

        # 2. 下跌触及网格下轨加仓
        if bar.close <= self.last_trade_price * (1.0 - self.step_pct):
            if self.cash >= bar.close * self.base_shares:
                self.buy(self.base_shares, reason="网格低吸加仓")
                self.last_trade_price = bar.close

        # 3. 上涨触及网格上轨高抛止盈
        elif bar.close >= self.last_trade_price * (1.0 + self.step_pct):
            if self.position.available_quantity >= self.base_shares:
                self.sell(self.base_shares, reason="网格高抛止盈")
                self.last_trade_price = bar.close
'''
    },
    {
        "name": "极端急跌重仓抄底 (Extreme Dip)",
        "description": "大盘或核心资产年内极端暴跌 15% 以上时果断重仓介入，反弹至均线平仓",
        "symbol": "510300.SH.ETF",
        "code": '''from quant_core.core.base_strategy import BaseStrategy
from quant_core.core.models import Bar

class ExtremeDipHeavyStrategy(BaseStrategy):
    """
    极端急跌重仓抄底策略 (QuantCore 2.0 极简范式)：
    - 监控 120 日内最高价的高位回撤幅度；
    - 当自高点回撤超过 15% 且当前无持仓时，果断调仓至 90% 仓位重仓抄底；
    - 当价格重回 60 日均线之上时，分批结利降低风险暴露。
    """
    def __init__(self, dip_threshold: float = 0.15, ma_period: int = 60):
        super().__init__(name="ExtremeDip", params={"dip": dip_threshold, "ma": ma_period})
        self.dip_threshold = dip_threshold
        self.ma_period = ma_period

    def on_bar(self, bar: Bar):
        peak_high = bar.highest(120)
        if peak_high <= 0:
            return

        drawdown_from_peak = (peak_high - bar.close) / peak_high

        # 1. 触发极端超跌：一次性 90% 仓位重仓建仓
        if drawdown_from_peak >= self.dip_threshold and not self.position:
            self.order_target_percent(0.90, reason=f"暴跌{drawdown_from_peak:.1%}极端抄底")

        # 2. 价格回归均线之上：减仓至 20% 止盈
        elif bar.close > bar.sma(self.ma_period) and self.position:
            self.order_target_percent(0.20, reason="价格回归均线减仓止盈")
'''
    },
    {
        "name": "达利欧全球全天候大类资产配置策略 (Ray Dalio All-Weather)",
        "description": "全球经典风险平价多资产配置，按30%股票、40%长债、15%中债、7.5%黄金、7.5%商品定期动态再平衡，穿越宏观经济四象限",
        "symbol": "510300.SH.ETF",
        "code": '''from quant_core.core.base_strategy import BaseStrategy
from quant_core.core.models import Bar

class AllWeatherStrategy(BaseStrategy):
    """
    达利欧全球全天候大类资产配置策略 (Ray Dalio All-Weather Portfolio - QuantCore 2.0)：
    - 股票权益 (30%): 捕捉经济繁荣增长红利 (如 510300 沪深300 / 标普500)
    - 长期债券 (40%): 抵御经济衰退通缩危机 (如 511010 国债ETF)
    - 中期纯债 (15%): 平滑组合净值波动与流动性
    - 黄金资产 (7.5%): 抵御货币超发与通胀风险 (如 518880 黄金ETF)
    - 大宗商品 (7.5%): 抵御恶性通货膨胀与供应链冲击
    """
    def __init__(
        self,
        stock_weight: float = 0.30,
        long_bond_weight: float = 0.40,
        inter_bond_weight: float = 0.15,
        gold_weight: float = 0.075,
        commodity_weight: float = 0.075,
        rebalance_band: float = 0.03,
        rebalance_interval: int = 20,
        single_symbol_target: float = 0.40
    ):
        params = {
            "stock_weight": stock_weight,
            "long_bond_weight": long_bond_weight,
            "inter_bond_weight": inter_bond_weight,
            "gold_weight": gold_weight,
            "commodity_weight": commodity_weight,
            "rebalance_band": rebalance_band,
            "rebalance_interval": rebalance_interval,
            "single_symbol_target": single_symbol_target
        }
        super().__init__(name="RayDalioAllWeather", params=params)
        self.stock_weight = stock_weight
        self.long_bond_weight = long_bond_weight
        self.inter_bond_weight = inter_bond_weight
        self.gold_weight = gold_weight
        self.commodity_weight = commodity_weight
        self.rebalance_band = rebalance_band
        self.rebalance_interval = rebalance_interval
        self.single_symbol_target = single_symbol_target
        self.counter = 0

    def _determine_symbol_target_weight(self, symbol: str) -> float:
        sym_lower = symbol.lower()
        if any(kw in sym_lower for kw in ["518880", "159934", "gold", "黄金"]):
            return self.gold_weight
        elif any(kw in sym_lower for kw in ["511010", "511260", "bond", "国债"]):
            return self.long_bond_weight
        elif any(kw in sym_lower for kw in ["159981", "commodity", "豆粕", "商品"]):
            return self.commodity_weight
        elif any(kw in sym_lower for kw in ["510300", "510500", "stock", "etf", "300"]):
            return self.stock_weight
        return self.single_symbol_target

    def on_bar(self, bar: Bar):
        self.counter += 1
        # 每隔固定周期进行组合再平衡 (或首根 K 线初始建仓)
        if self.counter % self.rebalance_interval != 0 and self.counter != 1:
            return

        total_equity = self.equity
        if total_equity <= 0:
            return

        target_pct = self._determine_symbol_target_weight(bar.symbol)
        pos = self.positions.get(bar.symbol)
        current_mv = pos.market_value if pos else 0.0
        current_pct = current_mv / total_equity

        # 首次建仓或偏离度突破容忍带宽时触发再平衡
        if self.counter == 1 or abs(current_pct - target_pct) >= self.rebalance_band:
            action = "全天候初始建仓" if self.counter == 1 else ("止盈降权" if current_pct > target_pct else "低位补齐增配")
            self.order_target_percent(
                bar.symbol,
                target_pct,
                reason=f"All-Weather {action} ({current_pct:.1%} -> {target_pct:.1%})"
            )
'''
    }
]

# -------------------------------------------------------------
# Pydantic Schemas
# -------------------------------------------------------------
class StrategyCreate(BaseModel):
    name: str = Field(..., max_length=128, description="策略名称")
    description: Optional[str] = Field(None, max_length=512, description="策略描述")
    code: str = Field(..., description="Python 策略源代码")
    symbol: str = Field(default="510300.SH.ETF", max_length=32, description="默认回测标的")

class StrategyUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=128)
    description: Optional[str] = Field(None, max_length=512)
    code: Optional[str] = None
    symbol: Optional[str] = None

class StrategyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    description: Optional[str] = None
    code: str
    symbol: str
    created_at: datetime.datetime
    updated_at: datetime.datetime


class BacktestRecordCreate(BaseModel):
    strategy_id: Optional[int] = None
    strategy_name: str = Field(..., max_length=128)
    symbol: str = Field(..., max_length=32)
    start_date: str = Field(..., max_length=32)
    end_date: Optional[str] = Field(None, max_length=32)
    initial_cash: float
    final_equity: float
    total_return: float
    annualized_return: float
    max_drawdown: float
    sharpe_ratio: float
    win_rate: float
    total_trades: int

class BacktestRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    strategy_id: Optional[int] = None
    strategy_name: str
    symbol: str
    start_date: str
    end_date: Optional[str] = None
    initial_cash: float
    final_equity: float
    total_return: float
    annualized_return: float
    max_drawdown: float
    sharpe_ratio: float
    win_rate: float
    total_trades: int
    created_at: datetime.datetime


# -------------------------------------------------------------
# 1. 个人策略库 API (User Strategies)
# -------------------------------------------------------------
@router.get("/strategies", response_model=List[StrategyOut])
async def list_user_strategies(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取当前登录用户的所有自定义策略列表，若为空则自动初始化基础预置策略库"""
    stmt = (
        select(UserStrategy)
        .where(UserStrategy.user_id == current_user.id)
        .order_by(UserStrategy.id.asc())
    )
    result = await db.execute(stmt)
    strategies = list(result.scalars().all())

    # 若用户的策略库中尚未包含任何预置策略（如老用户数据迁移、或首次访问），自动为其补全 4 套初始标准策略
    preset_names = {p["name"] for p in DEFAULT_PRESET_STRATEGIES}
    existing_names = {s.name for s in strategies}
    if not (existing_names & preset_names):
        for preset in DEFAULT_PRESET_STRATEGIES:
            strat = UserStrategy(
                user_id=current_user.id,
                name=preset["name"],
                description=preset["description"],
                code=preset["code"],
                symbol=preset["symbol"]
            )
            db.add(strat)
        await db.commit()

        # 重新获取已写入持久化数据库的策略列表
        result = await db.execute(stmt)
        strategies = list(result.scalars().all())

    return strategies


@router.post("/strategies", response_model=StrategyOut, status_code=status.HTTP_201_CREATED)
async def create_user_strategy(
    req: StrategyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """保存/新建个人量化策略 (普通用户限额 10 套，VIP 无限制)"""
    if not current_user.is_vip:
        cnt_stmt = select(func.count(UserStrategy.id)).where(UserStrategy.user_id == current_user.id)
        cnt = (await db.execute(cnt_stmt)).scalar() or 0
        if cnt >= 10:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="普通用户最多保存 10 套个人策略，请开通 VIP 解锁无限量云端策略库！"
            )

    strategy = UserStrategy(
        user_id=current_user.id,
        name=req.name.strip(),
        description=req.description,
        code=req.code,
        symbol=req.symbol
    )
    db.add(strategy)
    await db.commit()
    await db.refresh(strategy)
    return strategy


@router.get("/strategies/{strategy_id}", response_model=StrategyOut)
async def get_user_strategy(
    strategy_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取指定单套策略详情"""
    stmt = select(UserStrategy).where(
        UserStrategy.id == strategy_id,
        UserStrategy.user_id == current_user.id
    )
    result = await db.execute(stmt)
    strat = result.scalar_one_or_none()
    if not strat:
        raise HTTPException(status_code=404, detail="策略未找到或无权访问")
    return strat


@router.put("/strategies/{strategy_id}", response_model=StrategyOut)
async def update_user_strategy(
    strategy_id: int,
    req: StrategyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """修改/更新已有策略的代码与参数"""
    stmt = select(UserStrategy).where(
        UserStrategy.id == strategy_id,
        UserStrategy.user_id == current_user.id
    )
    result = await db.execute(stmt)
    strat = result.scalar_one_or_none()
    if not strat:
        raise HTTPException(status_code=404, detail="策略未找到或无权修改")

    if req.name is not None:
        strat.name = req.name.strip()
    if req.description is not None:
        strat.description = req.description
    if req.code is not None:
        strat.code = req.code
    if req.symbol is not None:
        strat.symbol = req.symbol

    await db.commit()
    await db.refresh(strat)
    return strat


@router.delete("/strategies/{strategy_id}")
async def delete_user_strategy(
    strategy_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """删除指定个人策略"""
    stmt = select(UserStrategy).where(
        UserStrategy.id == strategy_id,
        UserStrategy.user_id == current_user.id
    )
    result = await db.execute(stmt)
    strat = result.scalar_one_or_none()
    if not strat:
        raise HTTPException(status_code=404, detail="策略未找到或已删除")

    await db.delete(strat)
    await db.commit()
    return {"message": "策略已成功删除", "id": strategy_id}


# -------------------------------------------------------------
# 2. 用户历史回测归档记录 API (Backtest Records)
# -------------------------------------------------------------
@router.get("/backtests", response_model=List[BacktestRecordOut])
async def list_user_backtests(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取当前用户所有已归档的历史回测记录列表"""
    stmt = (
        select(BacktestRecord)
        .where(BacktestRecord.user_id == current_user.id)
        .order_by(BacktestRecord.created_at.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/backtests", response_model=BacktestRecordOut, status_code=status.HTTP_201_CREATED)
async def create_user_backtest(
    req: BacktestRecordCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """将一次成功的回测绩效与关键参数归档到当前用户档案"""
    record = BacktestRecord(
        user_id=current_user.id,
        strategy_id=req.strategy_id,
        strategy_name=req.strategy_name,
        symbol=req.symbol,
        start_date=req.start_date,
        end_date=req.end_date,
        initial_cash=req.initial_cash,
        final_equity=req.final_equity,
        total_return=req.total_return,
        annualized_return=req.annualized_return,
        max_drawdown=req.max_drawdown,
        sharpe_ratio=req.sharpe_ratio,
        win_rate=req.win_rate,
        total_trades=req.total_trades
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


@router.delete("/backtests/{record_id}")
async def delete_user_backtest(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """删除指定的历史回测记录"""
    stmt = select(BacktestRecord).where(
        BacktestRecord.id == record_id,
        BacktestRecord.user_id == current_user.id
    )
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="回测记录未找到或已删除")

    await db.delete(record)
    await db.commit()
    return {"message": "回测记录已成功删除", "id": record_id}


# -------------------------------------------------------------
# 3. 用户自选股票池/组合 API (User Watchlists)
# -------------------------------------------------------------
DEFAULT_PRESET_WATCHLISTS = [
    {
        "name": "🛡️ 达利欧全天候大类资产篮子",
        "description": "全球经典风险平价资产配置：核心权益、长短端国债与黄金商品宏观对冲",
        "symbols": ["510300.SH.ETF", "511010.SH.BOND", "518880.SH.ETF", "159981.SZ.ETF"]
    },
    {
        "name": "💰 高股息红利现金流组合",
        "description": "精选高分红、低波动央国企与红利主题基金",
        "symbols": ["510880.SH.ETF", "515100.SH.ETF", "512800.SH.ETF"]
    },
    {
        "name": "🚀 核心宽基与科技成长池",
        "description": "大盘蓝筹+成长动量组合：沪深300、中证500与创业板核心",
        "symbols": ["510300.SH.ETF", "510500.SH.ETF", "159915.SZ.ETF", "588000.SH.ETF"]
    },
    {
        "name": "🍷 消费与新能源龙头白马池",
        "description": "白酒与新质生产力核心资产精选",
        "symbols": ["600519.SH", "000858.SZ", "300750.SZ", "002594.SZ"]
    }
]

DEFAULT_PRESET_HOLDINGS = [
    {"symbol": "510300.SH.ETF", "name": "沪深300 ETF", "quantity": 10000.0, "avg_cost": 3.750},
    {"symbol": "510880.SH.ETF", "name": "红利 ETF", "quantity": 15000.0, "avg_cost": 2.920},
    {"symbol": "511010.SH.BOND", "name": "国债 ETF", "quantity": 500.0, "avg_cost": 105.20},
    {"symbol": "518880.SH.ETF", "name": "黄金 ETF", "quantity": 6000.0, "avg_cost": 5.40},
]


class WatchlistCreate(BaseModel):
    name: str = Field(..., max_length=128, description="组合名称")
    description: Optional[str] = Field(None, max_length=512, description="组合描述")
    symbols: List[str] = Field(..., min_length=1, description="标的代码列表")


class WatchlistOut(BaseModel):
    id: int
    user_id: int
    name: str
    description: Optional[str] = None
    symbols: List[str]
    created_at: datetime.datetime
    updated_at: datetime.datetime


class WatchlistAddSymbolsReq(BaseModel):
    symbols: List[str] = Field(..., min_length=1, description="要追加的标的代码列表")


@router.get("/watchlists", response_model=List[WatchlistOut])
async def list_user_watchlists(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取用户自选组合列表，若为空自动初始化预置经典组合"""
    stmt = (
        select(UserWatchlist)
        .where(UserWatchlist.user_id == current_user.id)
        .order_by(UserWatchlist.created_at.asc())
    )
    result = await db.execute(stmt)
    items = result.scalars().all()

    if not items:
        # 首次访问自动初始化预置自选组合
        created_items = []
        for preset in DEFAULT_PRESET_WATCHLISTS:
            new_item = UserWatchlist(
                user_id=current_user.id,
                name=preset["name"],
                description=preset["description"],
                symbols=json.dumps(preset["symbols"], ensure_ascii=False)
            )
            db.add(new_item)
            created_items.append(new_item)
        await db.commit()
        for item in created_items:
            await db.refresh(item)
        items = created_items

    # 反序列化 symbols 为 List[str]
    response = []
    for w in items:
        try:
            syms = json.loads(w.symbols) if isinstance(w.symbols, str) else w.symbols
        except Exception:
            syms = []
        response.append(WatchlistOut(
            id=w.id,
            user_id=w.user_id,
            name=w.name,
            description=w.description,
            symbols=syms,
            created_at=w.created_at,
            updated_at=w.updated_at
        ))
    return response


@router.post("/watchlists", response_model=WatchlistOut, status_code=status.HTTP_201_CREATED)
async def create_user_watchlist(
    req: WatchlistCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """创建新的自选组合/股票池"""
    symbols_cleaned = [s.strip() for s in req.symbols if s.strip()]
    if not symbols_cleaned:
        raise HTTPException(status_code=400, detail="自选组合中至少包含一个有效标的代码")

    item = UserWatchlist(
        user_id=current_user.id,
        name=req.name.strip(),
        description=req.description.strip() if req.description else None,
        symbols=json.dumps(symbols_cleaned, ensure_ascii=False)
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)

    return WatchlistOut(
        id=item.id,
        user_id=item.user_id,
        name=item.name,
        description=item.description,
        symbols=symbols_cleaned,
        created_at=item.created_at,
        updated_at=item.updated_at
    )


@router.delete("/watchlists/{watchlist_id}")
async def delete_user_watchlist(
    watchlist_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """删除指定的自选组合"""
    stmt = select(UserWatchlist).where(
        UserWatchlist.id == watchlist_id,
        UserWatchlist.user_id == current_user.id
    )
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="自选组合未找到或已删除")

    await db.delete(item)
    await db.commit()
    return {"message": "自选组合已成功删除", "id": watchlist_id}


@router.post("/watchlists/{watchlist_id}/symbols", response_model=WatchlistOut)
async def add_symbols_to_watchlist(
    watchlist_id: int,
    req: WatchlistAddSymbolsReq,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """向用户的指定自选组合追加标的代码 (自动去重)"""
    stmt = select(UserWatchlist).where(
        UserWatchlist.id == watchlist_id,
        UserWatchlist.user_id == current_user.id
    )
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="自选组合未找到")

    current_symbols: List[str] = json.loads(item.symbols) if item.symbols else []
    for s in req.symbols:
        cleaned = s.strip()
        if cleaned and cleaned not in current_symbols:
            current_symbols.append(cleaned)

    item.symbols = json.dumps(current_symbols, ensure_ascii=False)
    item.updated_at = datetime.datetime.now(datetime.timezone.utc)
    await db.commit()
    await db.refresh(item)

    return WatchlistOut(
        id=item.id,
        user_id=item.user_id,
        name=item.name,
        description=item.description,
        symbols=current_symbols,
        created_at=item.created_at,
        updated_at=item.updated_at
    )


@router.delete("/watchlists/{watchlist_id}/symbols/{symbol}", response_model=WatchlistOut)
async def remove_symbol_from_watchlist(
    watchlist_id: int,
    symbol: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """从用户的指定自选组合中移除标的代码"""
    stmt = select(UserWatchlist).where(
        UserWatchlist.id == watchlist_id,
        UserWatchlist.user_id == current_user.id
    )
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="自选组合未找到")

    current_symbols: List[str] = json.loads(item.symbols) if item.symbols else []
    sym_target = symbol.strip().upper()
    current_symbols = [s for s in current_symbols if s.strip().upper() != sym_target]

    item.symbols = json.dumps(current_symbols, ensure_ascii=False)
    item.updated_at = datetime.datetime.now(datetime.timezone.utc)
    await db.commit()
    await db.refresh(item)

    return WatchlistOut(
        id=item.id,
        user_id=item.user_id,
        name=item.name,
        description=item.description,
        symbols=current_symbols,
        created_at=item.created_at,
        updated_at=item.updated_at
    )


# -------------------------------------------------------------
# 4. 用户资产持仓 API (User Holdings)
# -------------------------------------------------------------
class HoldingItem(BaseModel):
    symbol: str = Field(..., max_length=32, description="标的代码 (如 510300.SH.ETF)")
    name: str = Field(..., max_length=64, description="标的名称")
    quantity: float = Field(default=100.0, ge=0, description="持仓股数")
    avg_cost: float = Field(default=0.0, ge=0, description="持仓成本均价 (CNY)")


class HoldingListUpdate(BaseModel):
    holdings: List[HoldingItem]


class HoldingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    symbol: str
    name: str
    quantity: float
    avg_cost: float
    created_at: datetime.datetime
    updated_at: datetime.datetime


@router.get("/holdings", response_model=List[HoldingOut])
async def list_user_holdings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取当前用户的持仓列表，若为空自动载入默认模拟持仓"""
    stmt = (
        select(UserHolding)
        .where(UserHolding.user_id == current_user.id)
        .order_by(UserHolding.created_at.asc())
    )
    result = await db.execute(stmt)
    items = result.scalars().all()

    if not items:
        created_items = []
        for h in DEFAULT_PRESET_HOLDINGS:
            item = UserHolding(
                user_id=current_user.id,
                symbol=h["symbol"],
                name=h["name"],
                quantity=h["quantity"],
                avg_cost=h["avg_cost"]
            )
            db.add(item)
            created_items.append(item)
        await db.commit()
        for item in created_items:
            await db.refresh(item)
        items = created_items

    return items


@router.put("/holdings", response_model=List[HoldingOut])
async def update_user_holdings(
    req: HoldingListUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """全量更新用户持仓列表"""
    # 1. 清空旧有持仓
    await db.execute(delete(UserHolding).where(UserHolding.user_id == current_user.id))

    # 2. 插入新持仓
    created_items = []
    for h in req.holdings:
        if not h.symbol.strip():
            continue
        new_holding = UserHolding(
            user_id=current_user.id,
            symbol=h.symbol.strip(),
            name=h.name.strip() or h.symbol.strip(),
            quantity=h.quantity,
            avg_cost=h.avg_cost
        )
        db.add(new_holding)
        created_items.append(new_holding)

    await db.commit()
    for item in created_items:
        await db.refresh(item)
    return created_items

