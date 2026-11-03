from sqlalchemy.ext.asyncio import AsyncSession
from app.models.merchant import Merchant
from sqlmodel import select
from loguru import logger
from typing import Tuple


async def create_merchant(whatsapp_no: str, db: AsyncSession) -> Tuple[Merchant, bool]:
    """create merchant helper"""

    result = await db.execute(
        select(Merchant).where(Merchant.whatsapp_no == whatsapp_no)
    )
    existing_merchant = result.scalars().first()

    if existing_merchant:
        logger.info(f"Merchant with whatsapp number {whatsapp_no} already exists.")
        return existing_merchant, False
    
    new_merchant = Merchant(whatsapp_no=whatsapp_no)
    db.add(new_merchant)
    await db.commit()
    await db.refresh(new_merchant)
    logger.info(f"Merchant with whatsapp number: {whatsapp_no} created successfully.")
    return new_merchant, True