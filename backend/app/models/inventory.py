from sqlmodel import SQLModel, Field
from uuid import uuid4, UUID
from datetime import datetime
from enum import StrEnum

class StockAvailability(StrEnum):
    """Model for stock availability"""

    INSTOCK = "in-stock"
    OUTOFSTOCK = "out-of-stock"
    

class Inventory(SQLModel, table=True):
    """Entity for storing items/goods"""

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    merchant_id: UUID = Field(foreign_key="merchant.id")
    item_name: str = Field(...)
    quantity: int = Field(...)
    price: float = Field(...)
    unit_sold: float = Field(...)
    bought_at: float = Field(...)
    sold_at: float = Field(...)
    stock_available: StockAvailability = Field(default=StockAvailability.INSTOCK)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    