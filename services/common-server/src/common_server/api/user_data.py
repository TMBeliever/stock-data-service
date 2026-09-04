import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from common_server.database import get_db
from common_server.models import User, UserStrategy, BacktestRecord
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
    经典双均线交叉策略 (Dual Moving Average Cross)：
    - MA(5) 上穿 MA(20) 金叉：以 80% 目标仓位买入建仓；
    - MA(5) 下穿 MA(20) 死叉：全部平仓落袋为安。
    """
    def __init__(self, fast_period: int = 5, slow_period: int = 20):
        super().__init__(name="DualMA", params={"fast": fast_period, "slow": slow_period})
        self.fast = fast_period
        self.slow = slow_period

    def on_bar(self, bar: Bar):
        symbol = bar.symbol
        closes = self.context.get_closes(symbol, n=self.slow + 2)
        if len(closes) < self.slow + 1:
            return

        ma_fast_prev = sum(closes[-self.fast - 1 : -1]) / self.fast
        ma_fast_curr = sum(closes[-self.fast :]) / self.fast

        ma_slow_prev = sum(closes[-self.slow - 1 : -1]) / self.slow
        ma_slow_curr = sum(closes[-self.slow :]) / self.slow

        pos = self.get_position(symbol)

        # 1. 金叉买入 (Golden Cross)
        if ma_fast_prev <= ma_slow_prev and ma_fast_curr > ma_slow_curr:
            if pos.quantity == 0:
                self.order_target_percent(symbol, 0.8, reason="金叉开仓")

        # 2. 死叉卖出 (Death Cross)
        elif ma_fast_prev >= ma_slow_prev and ma_fast_curr < ma_slow_curr:
            if pos.available_quantity > 0:
                self.close_position(symbol, reason="死叉平仓")
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
    智能估值分位数定投策略：
    - 在 250 日滚动窗口中计算价格历史分位数；
    - 分位数 <= 20% (极度低估): 加码 2.0 倍基准金额买入；
    - 分位数 >= 85% (严重高估): 减仓 20% 主动止盈防回撤。
    """
    def __init__(self, base_amount: float = 2000.0, window: int = 250):
        super().__init__(name="SmartDCA", params={"base_amount": base_amount, "window": window})
        self.base_amount = base_amount
        self.window = window
        self.bar_counter = 0

    def on_bar(self, bar: Bar):
        self.bar_counter += 1
        symbol = bar.symbol
        closes = self.context.get_closes(symbol, n=self.window)
        if len(closes) < 30:
            return

        # 每 5 个交易日评估一次定投
        if self.bar_counter % 5 != 0:
            return

        curr_price = bar.close
        less_count = sum(1 for c in closes if c < curr_price)
        pct = less_count / len(closes)

        pos = self.get_position(symbol)
        portfolio = self.context.portfolio

        if pct <= 0.20 and portfolio.cash >= self.base_amount * 2:
            qty = int((self.base_amount * 2.0) / curr_price // 100) * 100
            if qty > 0:
                self.buy(symbol, qty, price=curr_price, reason=f"低估加倍定投(分位{pct:.1%})")
        elif pct <= 0.50 and portfolio.cash >= self.base_amount:
            qty = int(self.base_amount / curr_price // 100) * 100
            if qty > 0:
                self.buy(symbol, qty, price=curr_price, reason=f"合理估值定投(分位{pct:.1%})")
        elif pct >= 0.85 and pos.available_quantity >= 500:
            sell_qty = min(pos.available_quantity, int(pos.available_quantity * 0.2 // 100) * 100)
            if sell_qty > 0:
                self.sell(symbol, sell_qty, price=curr_price, reason=f"高估主动止盈(分位{pct:.1%})")
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
    动态自适应网格策略：
    - 以 60 日均线为中枢基准；
    - 价格下跌超 2.5% 触及下轨分批加仓；
    - 价格上涨超 2.5% 触及上轨获利止盈。
    """
    def __init__(self, step_pct: float = 0.025, base_shares: int = 1000):
        super().__init__(name="GridTrading", params={"step": step_pct})
        self.step_pct = step_pct
        self.base_shares = base_shares
        self.last_trade_price = 0.0

    def on_bar(self, bar: Bar):
        symbol = bar.symbol
        closes = self.context.get_closes(symbol, n=60)
        if len(closes) < 30:
            return

        curr_price = bar.close
        pos = self.get_position(symbol)

        # 初始建底仓
        if self.last_trade_price == 0.0:
            self.order_target_percent(symbol, 0.4, reason="网格初始化底仓")
            self.last_trade_price = curr_price
            return

        # 下跌触及网格下轨加仓
        if curr_price <= self.last_trade_price * (1.0 - self.step_pct):
            if self.context.portfolio.cash >= curr_price * self.base_shares:
                self.buy(symbol, self.base_shares, price=curr_price, reason="网格低吸加仓")
                self.last_trade_price = curr_price

        # 上涨触及网格上轨止盈
        elif curr_price >= self.last_trade_price * (1.0 + self.step_pct):
            if pos.available_quantity >= self.base_shares:
                self.sell(symbol, self.base_shares, price=curr_price, reason="网格高抛止盈")
                self.last_trade_price = curr_price
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
    极端急跌重仓抄底策略：
    - 监控 120 日内最高价的高位回撤幅度；
    - 当自高点回撤超过 15% 且触底阳线反弹时，果断调仓至 90% 仓位重仓抄底；
    - 当价格重回 60 日均线之上时，分批结利降低风险暴露。
    """
    def __init__(self, dip_threshold: float = 0.15, ma_period: int = 60):
        super().__init__(name="ExtremeDip", params={"dip": dip_threshold, "ma": ma_period})
        self.dip_threshold = dip_threshold
        self.ma_period = ma_period

    def on_bar(self, bar: Bar):
        symbol = bar.symbol
        closes = self.context.get_closes(symbol, n=120)
        if len(closes) < 60:
            return

        max_close = max(closes)
        curr_price = bar.close
        drawdown_from_peak = (max_close - curr_price) / max_close
        pos = self.get_position(symbol)

        ma_val = sum(closes[-self.ma_period :]) / self.ma_period

        # 触发极端超跌：一次性重仓建仓
        if drawdown_from_peak >= self.dip_threshold and pos.quantity == 0:
            self.order_target_percent(symbol, 0.90, reason=f"暴跌{drawdown_from_peak:.1%}极端抄底")

        # 均线修复出场
        elif curr_price > ma_val and pos.available_quantity > 0:
            self.order_target_percent(symbol, 0.20, reason="价格回归均线减仓止盈")
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

    # 若用户策略库完全为空，自动为该用户持久化初始化 4 套标准经典策略
    if not strategies:
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
