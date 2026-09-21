import datetime
from enum import Enum
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Text,
    DateTime,
)
from asset_server.database import Base


class AssetCategory(str, Enum):
    """全品类大类资产分类"""
    CASH = "CASH"                  # 现金、活期存款、零钱、可用资金
    EQUITY = "EQUITY"              # 股票、权益类 ETF、场内外基金
    FIXED_INCOME = "FIXED_INCOME"  # 国债、可转债、银行定期理财、大额存单
    COMMODITY = "COMMODITY"        # 黄金、白银、大宗商品
    CRYPTO = "CRYPTO"              # 数字货币 (BTC/ETH/USDT等)
    REAL_ESTATE = "REAL_ESTATE"    # 房产物业、车位等不动产
    LIABILITY = "LIABILITY"        # 负债项 (房贷余额、车贷、消费信贷等，负向资产)
    OTHER = "OTHER"                # 其他另类资产


class AssetItem(Base):
    """全景资产核心实体表"""
    __tablename__ = "asset_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True, doc="归属用户 ID")
    category = Column(String(32), nullable=False, default=AssetCategory.EQUITY.value, index=True, doc="资产大类")
    name = Column(String(128), nullable=False, doc="资产名称 (如: 沪深300 ETF, 招行定期存款, 自住房产)")
    symbol = Column(String(64), nullable=True, index=True, doc="标的代码 (股票/ETF/加密货币有代码，现金/房产等无代码)")
    amount = Column(Float, nullable=False, default=0.0, doc="持有数量/份额/本金")
    cost_price = Column(Float, nullable=False, default=0.0, doc="买入成本均价 (单价)")
    manual_price = Column(Float, nullable=True, doc="手动估值单价 (无行情代码资产使用)")
    currency = Column(String(8), nullable=False, default="CNY", doc="计价币种")
    note = Column(Text, nullable=True, doc="备注信息")

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
